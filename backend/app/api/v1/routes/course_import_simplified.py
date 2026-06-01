"""Simplified course import using Ollama AI and unified format."""
import httpx
import json
import re
from datetime import datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.v1.routes.unified_course_format import (
    UnifiedAssignment,
    UnifiedClassEvent,
    deduplicate_assignments,
    deduplicate_class_events,
)
from app.core.config.settings import settings

router = APIRouter(tags=["course-import"])


class CourseImportResponse(BaseModel):
    """Response from course import."""
    course_url: str
    course_name: str
    assignments_imported: int
    class_events_imported: int
    total_imported: int
    warnings: list[str] = []
    class_events: list[dict] = []  # UnifiedClassEvent as dict
    assignments: list[dict] = []   # UnifiedAssignment as dict


def extract_json_object(response_text: str) -> str | None:
    """Extract the first balanced JSON object from an LLM response."""
    text = response_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)

    start = text.find("{")
    if start == -1:
        return None

    depth = 0
    in_string = False
    escaped = False

    for index in range(start, len(text)):
        char = text[index]

        if escaped:
            escaped = False
            continue

        if char == "\\" and in_string:
            escaped = True
            continue

        if char == '"':
            in_string = not in_string
            continue

        if in_string:
            continue

        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]

    return text[start:]


def parse_ollama_json(response_text: str) -> dict:
    """Parse Ollama JSON and turn invalid model output into a controlled API error."""
    json_str = extract_json_object(response_text)
    if not json_str:
        raise HTTPException(status_code=502, detail="Ollama response did not contain a JSON object")

    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as original_error:
        # LLMs commonly add trailing commas even when asked for strict JSON.
        repaired_json = re.sub(r",\s*([}\]])", r"\1", json_str)
        if repaired_json != json_str:
            try:
                parsed = json.loads(repaired_json)
            except json.JSONDecodeError:
                parsed = None
        else:
            parsed = None

        if parsed is None:
            start = max(original_error.pos - 120, 0)
            end = min(original_error.pos + 120, len(json_str))
            snippet = json_str[start:end].replace("\n", "\\n")
            raise HTTPException(
                status_code=502,
                detail=(
                    "Ollama returned invalid JSON "
                    f"at line {original_error.lineno}, column {original_error.colno}: "
                    f"{original_error.msg}. Snippet: {snippet}"
                ),
            )

    if not isinstance(parsed, dict):
        raise HTTPException(status_code=502, detail="Ollama JSON response must be an object")

    parsed.setdefault("class_events", [])
    parsed.setdefault("assignments", [])
    return parsed


def is_valid_iso_date(value: object) -> bool:
    """Return True when value is a real YYYY-MM-DD date."""
    if not isinstance(value, str):
        return False

    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False

    return True


async def fetch_course_page(course_url: str) -> str:
    """Fetch course page HTML."""
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            response = await client.get(course_url)
            response.raise_for_status()
            return response.text
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Could not fetch {course_url}: {str(e)}")


async def parse_with_ollama(html: str, course_name: str) -> dict:
    """Parse course HTML with Ollama AI."""
    # Extract text from HTML (remove tags)
    text = re.sub(r'<[^>]+>', ' ', html)
    text = re.sub(r'\s+', ' ', text)[:8000]  # Limit to 8000 chars

    prompt = f"""Extract ALL course events and assignments from this course page text.

IMPORTANT: Extract ACTUAL DATES from the calendar/schedule, not from URL fragments.
Dates must be in YYYY-MM-DD format (e.g., 2026-04-10, 2026-05-15, etc.).
Only include events or assignments with explicit calendar dates.
If an item only has a quarter code like 26sp, a day of week, or a recurring time, omit it.

For LECTURES, LABS, SECTIONS, EXAMS, etc., provide:
- event_name: e.g., "Lecture 1", "Lab A", "Midterm Exam"
- event_type: lecture, lab, section, discussion, exam, office_hours
- date: YYYY-MM-DD format (ACTUAL EVENT DATE, not URL date)
- start_time: HH:MM format (24h), or null if no start time is shown
- end_time: HH:MM format (24h), or null if no end time is shown
- location: room/building or "Online" or null
- description: brief description

For HOMEWORK, ASSIGNMENTS, PROJECTS, etc., provide:
- assignment_name: e.g., "HW1", "Project 2", "Midterm"
- assignment_type: homework, project, exam, quiz, lab, reading
- due_date: YYYY-MM-DD format (ACTUAL DUE DATE)
- due_time: HH:MM format (24h), or null if no due time is shown
- points: integer or null
- description: brief description or empty string if not specified
- submission_method: Canvas, email, in-person, etc. or null
- requirements: list of requirements (empty list if none)
- is_individual: true/false
- is_group: true/false
- late_policy: description or null

Do not invent midnight or 00:00 for missing times. Use null for missing times.
When a lecture/lab/section row includes both a start and an end time, include both times exactly.

Course: {course_name}
Text:
{text}

Return ONLY valid JSON (no markdown, no code blocks) with this structure.
Use empty arrays when no items are found. Do not include placeholders, ellipses, comments, or trailing commas:
{{
  "course_name": "{course_name}",
  "class_events": [],
  "assignments": []
}}
"""

    try:
        ollama_url = f"{settings.ollama_host.rstrip('/')}/api/generate"
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                ollama_url,
                json={
                    "model": "mistral",
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0},
                },
            )

        if response.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Ollama error: {response.text}")

        result = response.json()
        response_text = result.get("response", "")
        return parse_ollama_json(response_text)

    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Ollama server not running. Start with: ollama serve",
        )


def convert_to_unified_format(
    parsed_data: dict,
    course_url: str,
) -> tuple[list[UnifiedAssignment], list[UnifiedClassEvent], list[str]]:
    """Convert parsed data to unified format."""
    course_name = parsed_data.get("course_name", "Unknown Course")
    assignments = []
    class_events = []
    warnings = []

    # Convert assignments
    for raw_assignment in parsed_data.get("assignments", []):
        try:
            if not isinstance(raw_assignment, dict):
                warnings.append(f"Skipped malformed assignment: {raw_assignment}")
                continue

            if not is_valid_iso_date(raw_assignment.get("due_date")):
                warnings.append(
                    f"Skipped assignment with invalid due_date: {raw_assignment.get('assignment_name', 'Unknown')}"
                )
                continue

            assignment = UnifiedAssignment(
                assignment_name=raw_assignment.get("assignment_name", "Unknown"),
                assignment_type=raw_assignment.get("assignment_type", "assignment"),
                due_date=raw_assignment.get("due_date", ""),
                due_time=raw_assignment.get("due_time"),
                points=raw_assignment.get("points"),
                description=raw_assignment.get("description", ""),
                submission_method=raw_assignment.get("submission_method"),
                requirements=raw_assignment.get("requirements", []),
                is_individual=raw_assignment.get("is_individual", True),
                is_group=raw_assignment.get("is_group", False),
                late_policy=raw_assignment.get("late_policy"),
                course_name=course_name,
                source_url=course_url,
            )
            assignments.append(assignment)
        except Exception as e:
            warnings.append(
                f"Skipped assignment {raw_assignment.get('assignment_name', 'Unknown')}: {e}"
            )
            print(f"Error converting assignment: {e}")

    # Convert class events
    for raw_event in parsed_data.get("class_events", []):
        try:
            if not isinstance(raw_event, dict):
                warnings.append(f"Skipped malformed event: {raw_event}")
                continue

            if not is_valid_iso_date(raw_event.get("date")):
                warnings.append(
                    f"Skipped event with invalid date: {raw_event.get('event_name', 'Class Event')}"
                )
                continue

            event = UnifiedClassEvent(
                event_name=raw_event.get("event_name", "Class Event"),
                event_type=raw_event.get("event_type", "lecture"),
                date=raw_event.get("date", ""),
                start_time=raw_event.get("start_time", "09:00"),
                end_time=raw_event.get("end_time"),
                location=raw_event.get("location"),
                description=raw_event.get("description"),
                course_name=course_name,
                source_url=course_url,
            )
            class_events.append(event)
        except Exception as e:
            warnings.append(f"Skipped event {raw_event.get('event_name', 'Class Event')}: {e}")
            print(f"Error converting event: {e}")

    return assignments, class_events, warnings


async def save_to_calendar(
    user_id: str,
    assignments: list[UnifiedAssignment],
    class_events: list[UnifiedClassEvent],
) -> dict:
    """Save unified format events to calendar (Supabase).

    This function extracts information from unified events and saves to database.
    Currently a placeholder - will be connected to Supabase.
    """
    result = {
        "assignments_imported": 0,
        "assignments_failed": 0,
        "class_events_imported": 0,
        "class_events_failed": 0,
        "details": [],
    }

    # Save assignments
    for assignment in assignments:
        try:
            # TODO: Save to Supabase tasks table
            # supabase.table("tasks").insert({
            #     "user_id": user_id,
            #     "title": assignment.assignment_name,
            #     "due_date": assignment.due_date,
            #     "description": assignment.description,
            #     ...
            # }).execute()

            result["assignments_imported"] += 1
            result["details"].append(f"✅ {assignment.assignment_name} ({assignment.course_name})")
        except Exception as e:
            result["assignments_failed"] += 1
            result["details"].append(f"❌ {assignment.assignment_name}: {str(e)}")

    # Save class events
    for event in class_events:
        try:
            # TODO: Save to Supabase events table
            # supabase.table("events").insert({
            #     "user_id": user_id,
            #     "title": event.event_name,
            #     "start_time": f"{event.date}T{event.start_time}",
            #     "end_time": f"{event.date}T{event.end_time}",
            #     ...
            # }).execute()

            result["class_events_imported"] += 1
            result["details"].append(f"✅ {event.event_name} ({event.course_name})")
        except Exception as e:
            result["class_events_failed"] += 1
            result["details"].append(f"❌ {event.event_name}: {str(e)}")

    result["total_imported"] = result["assignments_imported"] + result["class_events_imported"]
    return result


@router.post("/", response_model=CourseImportResponse)
async def import_course(course_url: str) -> CourseImportResponse:
    """Import course using AI parsing and unified format."""

    # 1. Fetch course page
    html = await fetch_course_page(course_url)

    # 2. Extract course name from URL
    course_name = course_url.rstrip("/").split("/")[-2]

    # 3. Parse with Ollama AI
    parsed_data = await parse_with_ollama(html, course_name)

    # 4. Convert to unified format
    assignments, class_events, warnings = convert_to_unified_format(parsed_data, course_url)

    # 5. Deduplicate
    unique_assignments = deduplicate_assignments(assignments)
    unique_class_events = deduplicate_class_events(class_events)

    class_events_dict = [ev.model_dump() for ev in unique_class_events]
    assignments_dict = [asn.model_dump() for asn in unique_assignments]

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
