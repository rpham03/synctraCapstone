"""Course import route variant that uses the Colab course-import agent.

This file is intentionally separate from course_import.py so the existing
local Ollama-backed route can stay unchanged while the Colab server is tested.

To enable this route later, register it in backend/app/main.py:

    from app.api.v1.routes import course_import_colab
    app.include_router(
        course_import_colab.router,
        prefix="/api/v1/course-import-colab",
        tags=["course-import-colab"],
    )

Expected Colab server:

    tool/colab_course_import_agent_server.py

The Colab server exposes an Ollama-compatible POST /api/generate endpoint.
"""

from __future__ import annotations

import os
import re
from datetime import datetime

import httpx
from fastapi import APIRouter, HTTPException, Query

from app.api.v1.routes.course_import import (
    COURSE_REQUEST_HEADERS,
    CourseImportResponse,
    LLM_RESPONSE_SCHEMA,
    OLLAMA_COURSE_IMPORT_TIMEOUT_S,
    convert_to_unified_format,
    deduplicate_course_import_assignments,
    deduplicate_course_import_class_events,
    fetch_course_context_for_llm,
    fetch_course_page_with_url,
    infer_quarter_dates,
    merge_parsed_course_data,
    normalize_course_url,
    parse_ollama_json,
    parse_static_course_calendar,
    preprocess_html_for_llm,
    should_augment_assignment_estimates_with_ai,
    should_augment_with_ai,
)
from app.api.v1.routes.unified_course_format import (
    deduplicate_assignments,
    deduplicate_class_events,
)
from app.core.config.settings import settings


router = APIRouter(tags=["course-import-colab"])

DEFAULT_COLAB_MODEL = "Qwen/Qwen2.5-3B-Instruct"
COLAB_TIMEOUT = httpx.Timeout(
    float(
        os.getenv(
            "COLAB_COURSE_IMPORT_TIMEOUT",
            settings.colab_course_import_timeout or OLLAMA_COURSE_IMPORT_TIMEOUT_S,
        )
    ),
    connect=20.0,
)


def colab_agent_host(override: str | None = None) -> str:
    """Return the Colab tunnel URL without a trailing slash."""
    host = (
        override
        or settings.colab_course_import_host
        or os.getenv("COLAB_COURSE_IMPORT_HOST")
        or os.getenv("COLAB_AGENT_HOST")
        or ""
    ).strip()
    if not host:
        raise HTTPException(
            status_code=503,
            detail=(
                "Colab course import agent is not configured. Set "
                "COLAB_COURSE_IMPORT_HOST to the tunnel URL printed by "
                "tool/colab_course_import_agent_server.py."
            ),
        )
    return host.rstrip("/")


def colab_agent_model(override: str | None = None) -> str:
    """Return the model name sent to the Colab Ollama-compatible endpoint."""
    return (
        override
        or settings.colab_course_import_model
        or os.getenv("COLAB_COURSE_IMPORT_MODEL")
        or settings.course_import_model
        or DEFAULT_COLAB_MODEL
    ).strip()


def compact_course_content(html_or_context: str, max_chars: int = 24000) -> str:
    """Prepare HTML or already-pruned text for the remote model prompt."""
    if "<" in html_or_context and ">" in html_or_context:
        return preprocess_html_for_llm(html_or_context, max_chars=max_chars)

    text = re.sub(r"\n{3,}", "\n\n", html_or_context)
    text = re.sub(r"[ \t]+", " ", text)
    return text[:max_chars]


def build_colab_course_import_prompt(
    html_or_context: str,
    course_name: str,
    course_url: str = "",
) -> str:
    """Build the same extraction prompt expected by course_import.py."""
    text = compact_course_content(html_or_context, max_chars=24000)
    today = datetime.now().strftime("%Y-%m-%d")
    quarter = infer_quarter_dates(course_url)
    quarter_line = (
        f"Academic quarter runs from {quarter[0]} to {quarter[1]}.\n"
        if quarter else ""
    )

    return f"""Extract every course event from this page into the schema.

Today is {today}. Course: {course_name}.
{quarter_line}
Rules:
- Times must use 24h HH:MM (e.g. "23:59"). Use null when no time is given.
- Never output TBD, TBA, unknown, or "to be determined" as a name.
- If a lecture/section/lab has no listed topic, name it only by type ("Lecture", "Section").
- Use every Source URL section; schedule and assignment details may be on linked pages.
- assignment_type must be one of: homework, project, exam, quiz, lab, reading.
- event_type must be one of: lecture, lab, section, discussion, exam, office_hours.
- For each assignment, estimate focused work time as estimated_minutes for an
  average student, not an expert. Be conservative and include time for reading,
  setup, debugging, review, and revision. Use 30 minute increments; do not exceed 720.

Recurring schedules:
- If the page only describes a recurring pattern like "MWF 10:30-11:20" or
  "Tue/Thu 1:30-3:20" without specific dates, expand it into one entry per
  occurrence between the quarter start and end above.
- Skip US federal holidays and Thanksgiving/Veterans Day breaks if mentioned.
- Use 24h start_time and end_time exactly as written; do not invent times.

Example input snippet:
  "Lectures: MWF 10:30-11:20am, GUG 220
   HW1 due Friday 04/10/26 by 11:59pm
   Midterm: Wednesday May 13"

Example correct extraction, abbreviated:
  class_events: [
    {{"event_name":"Lecture","event_type":"lecture","date":"2026-03-30",
      "start_time":"10:30","end_time":"11:20","location":"GUG 220","description":null}},
    {{"event_name":"Lecture","event_type":"lecture","date":"2026-04-01",
      "start_time":"10:30","end_time":"11:20","location":"GUG 220","description":null}},
    {{"event_name":"Midterm","event_type":"exam","date":"2026-05-13",
      "start_time":null,"end_time":null,"location":null,"description":null}}
  ]
  assignments: [
    {{"assignment_name":"HW1","assignment_type":"homework","due_date":"2026-04-10",
      "due_time":"23:59","points":null,"description":"HW1 due Friday 04/10/26 by 11:59pm",
      "submission_method":null,"requirements":[],"is_individual":true,"is_group":false,
      "late_policy":null,"estimated_minutes":240}}
  ]

Page content:
{text}
"""


async def parse_with_colab_agent(
    html_or_context: str,
    course_name: str,
    course_url: str = "",
    *,
    host: str | None = None,
    model: str | None = None,
) -> dict:
    """Parse course content with the remote Colab agent server."""
    prompt = build_colab_course_import_prompt(
        html_or_context,
        course_name,
        course_url,
    )
    agent_host = colab_agent_host(host)
    agent_model = colab_agent_model(model)

    try:
        async with httpx.AsyncClient(timeout=COLAB_TIMEOUT) as client:
            response = await client.post(
                f"{agent_host}/api/generate",
                json={
                    "model": agent_model,
                    "prompt": prompt,
                    "stream": False,
                    "format": LLM_RESPONSE_SCHEMA,
                    "options": {"temperature": 0},
                },
                headers=COURSE_REQUEST_HEADERS,
            )
            response.raise_for_status()
    except httpx.ConnectError as exc:
        raise HTTPException(
            status_code=503,
            detail=(
                "Could not connect to the Colab course import agent. Start "
                "tool/colab_course_import_agent_server.py in Colab and set "
                "COLAB_COURSE_IMPORT_HOST to its public tunnel URL."
            ),
        ) from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(
            status_code=504,
            detail="Colab course import agent timed out while parsing the course page.",
        ) from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Colab course import agent error: {exc.response.text}",
        ) from exc

    result = response.json()
    response_text = result.get("response", "")
    return parse_ollama_json(response_text)


@router.get("/health")
async def health(
    colab_host: str | None = Query(default=None),
) -> dict:
    """Check that the Colab server is reachable."""
    host = colab_agent_host(colab_host)
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(f"{host}/health")
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Colab course import agent health check failed: {exc}",
        ) from exc

    return {
        "ok": True,
        "colab_host": host,
        "agent": payload,
    }


@router.post("/", response_model=CourseImportResponse)
async def import_course_with_colab(
    course_url: str,
    colab_host: str | None = Query(default=None),
    colab_model: str | None = Query(default=None),
    force_ai: bool = Query(
        default=False,
        description="When true, skip deterministic parsing and use Colab AI only.",
    ),
) -> CourseImportResponse:
    """Import a course using the Colab AI agent for the LLM step."""
    parse_warnings: list[str] = []
    requested_course_url = course_url
    course_url = normalize_course_url(course_url)
    if course_url != requested_course_url:
        parse_warnings.append(f"Using current UW quarter URL: {course_url}")

    html, resolved_course_url = await fetch_course_page_with_url(course_url)
    course_name = course_url.rstrip("/").split("/")[-2]
    parsed_data = None if force_ai else await parse_static_course_calendar(
        course_url,
        html,
        course_name,
        resolved_course_url,
    )

    if parsed_data is None:
        context_text = await fetch_course_context_for_llm(
            course_url,
            html,
            resolved_course_url,
        )
        parsed_data = await parse_with_colab_agent(
            context_text,
            course_name,
            course_url,
            host=colab_host,
            model=colab_model,
        )
    elif (
        settings.course_import_ai_augment
        or should_augment_with_ai(parsed_data)
        or should_augment_assignment_estimates_with_ai(parsed_data)
    ):
        context_text = await fetch_course_context_for_llm(
            course_url,
            html,
            resolved_course_url,
        )
        try:
            ai_data = await parse_with_colab_agent(
                context_text,
                course_name,
                course_url,
                host=colab_host,
                model=colab_model,
            )
            parsed_data = merge_parsed_course_data(parsed_data, ai_data)
        except HTTPException as exc:
            parse_warnings.append(f"Colab AI augmentation skipped: {exc.detail}")

    assignments, class_events, warnings = convert_to_unified_format(
        parsed_data,
        course_url,
    )
    warnings = [*parse_warnings, *warnings]

    unique_assignments = deduplicate_course_import_assignments(
        deduplicate_assignments(assignments)
    )
    unique_class_events = deduplicate_course_import_class_events(
        deduplicate_class_events(class_events)
    )

    class_events_dict = [event.model_dump() for event in unique_class_events]
    assignments_dict = [assignment.model_dump() for assignment in unique_assignments]

    return CourseImportResponse(
        course_url=course_url,
        course_name=parsed_data.get("course_name", course_name),
        assignments_imported=len(unique_assignments),
        class_events_imported=len(unique_class_events),
        total_imported=len(unique_assignments) + len(unique_class_events),
        class_events=class_events_dict,
        assignments=assignments_dict,
        warnings=warnings,
    )
