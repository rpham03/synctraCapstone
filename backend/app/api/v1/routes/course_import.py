"""Simplified course import using Ollama AI and unified format."""
import httpx
import json
import re
from datetime import datetime
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.v1.routes.events import (
    _CALENDAR_CANDIDATES,
    _html_fallback,
    _has_monthtable,
    _parse_events_source_json,
    _parse_monthtable,
)
from app.api.v1.routes.unified_course_format import (
    UnifiedAssignment,
    UnifiedClassEvent,
    deduplicate_assignments,
    deduplicate_class_events,
)

router = APIRouter(tags=["course-import"])

ASSIGNMENT_DUE_RE = re.compile(r"\b(?:due|deadline)\b", re.IGNORECASE)
CALENDAR_LINK_RE = re.compile(r"\b(?:calendar|schedule)\b", re.IGNORECASE)


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


def infer_event_type(title: str) -> str:
    """Infer a constrained event type from a calendar title."""
    lower_title = title.lower()
    if any(term in lower_title for term in ("exam", "midterm", "final")):
        return "exam"
    if "section" in lower_title:
        return "section"
    if "lab" in lower_title:
        return "lab"
    if "discussion" in lower_title:
        return "discussion"
    if "office hour" in lower_title:
        return "office_hours"
    return "lecture"


def infer_assignment_type(title: str) -> str:
    """Infer assignment type from a calendar title."""
    lower_title = title.lower()
    if "project" in lower_title:
        return "project"
    if "quiz" in lower_title:
        return "quiz"
    if "lab" in lower_title:
        return "lab"
    if "reading" in lower_title:
        return "reading"
    if any(term in lower_title for term in ("exam", "midterm", "final")):
        return "exam"
    return "homework"


def clean_calendar_text(text: str) -> str:
    """Normalize whitespace in scraped calendar labels."""
    return re.sub(r"\s+", " ", text).strip()


def infer_grid_item_type(class_names: set[str], title: str) -> str:
    """Infer event type from CSE grid-calendar CSS classes and title."""
    lower_classes = {class_name.lower() for class_name in class_names}
    if "exam" in lower_classes or any(term in title.lower() for term in ("exam", "midterm", "final")):
        return "exam"
    if "lab" in lower_classes:
        return "lab"
    if "section" in lower_classes:
        return "section"
    if "discussion" in lower_classes:
        return "discussion"
    if "office_hours" in lower_classes or "office-hours" in lower_classes:
        return "office_hours"
    return "lecture"


def parse_grid_calendar(soup) -> list[dict]:
    """Parse CSE calendar pages that use div.day[date] grid markup."""
    events = []
    for day in soup.select("#schedule.calendar .day[date], .calendar .day[date]"):
        date_str = day.get("date", "")
        if not is_valid_iso_date(date_str):
            continue

        events_container = day.find("div", class_="events")
        if not events_container:
            continue

        for item in events_container.find_all(["details", "div"], recursive=False):
            class_names = set(item.get("class", []))
            lower_classes = {class_name.lower() for class_name in class_names}
            if {"no", "meeting"}.issubset(lower_classes):
                continue

            if item.name == "details":
                summary = item.find("summary")
                title = clean_calendar_text(summary.get_text(" ", strip=True) if summary else "")
            else:
                title = clean_calendar_text(item.get_text(" ", strip=True))

            if not title:
                continue

            event_type = infer_grid_item_type(class_names, title)
            event_kind = "assignment" if "assignment" in lower_classes else "class_event"
            start_dt = datetime.fromisoformat(f"{date_str}T00:00:00")
            end_dt = datetime.fromisoformat(f"{date_str}T23:59:59")

            events.append({
                "id": f"{date_str}_{event_kind}_{len(events)}",
                "title": title,
                "start_time": start_dt.isoformat(),
                "end_time": end_dt.isoformat(),
                "source": "course",
                "is_fixed": True,
                "event_kind": event_kind,
                "event_type": event_type,
                "all_day": True,
            })

    return events


def parse_supported_calendar_soup(soup) -> list[dict]:
    """Parse known deterministic calendar formats from a BeautifulSoup document."""
    if _has_monthtable(soup):
        return _parse_monthtable(soup)

    return parse_grid_calendar(soup)


def calendar_event_to_unified(
    event: dict,
    course_name: str,
    course_url: str,
) -> tuple[dict | None, dict | None]:
    """Convert a deterministic calendar event into assignment or class-event dicts."""
    title = event.get("title", "Class Event")

    try:
        start_dt = datetime.fromisoformat(event["start_time"])
        end_dt = datetime.fromisoformat(event.get("end_time", event["start_time"]))
    except (KeyError, TypeError, ValueError):
        return None, None

    all_day = event.get("all_day") is True
    start_time = start_dt.strftime("%H:%M")
    end_time = end_dt.strftime("%H:%M")

    if event.get("event_kind") == "assignment" or ASSIGNMENT_DUE_RE.search(title):
        return {
            "assignment_name": title,
            "assignment_type": infer_assignment_type(title),
            "due_date": start_dt.date().isoformat(),
            "due_time": None if all_day else start_time,
            "points": None,
            "description": "",
            "submission_method": None,
            "requirements": [],
            "is_individual": True,
            "is_group": False,
            "late_policy": None,
            "course_name": course_name,
            "source_url": course_url,
        }, None

    return None, {
        "event_name": title,
        "event_type": event.get("event_type") or infer_event_type(title),
        "date": start_dt.date().isoformat(),
        "start_time": None if all_day else start_time,
        "end_time": None if all_day else end_time,
        "location": None,
        "description": None,
        "course_name": course_name,
        "source_url": course_url,
    }


def convert_calendar_events_to_unified(
    events: list[dict],
    course_name: str,
    course_url: str,
) -> dict:
    """Convert deterministic calendar parser output into the route response schema."""
    assignments = []
    class_events = []

    for event in events:
        assignment, class_event = calendar_event_to_unified(event, course_name, course_url)
        if assignment:
            assignments.append(assignment)
        if class_event:
            class_events.append(class_event)

    return {
        "course_name": course_name,
        "class_events": class_events,
        "assignments": assignments,
    }


async def parse_static_course_calendar(
    course_url: str,
    html: str,
    fallback_course_name: str,
) -> dict | None:
    """Try the deterministic UW/generic course calendar parser before using AI."""
    base_url = urljoin(course_url, ".")
    main_soup = BeautifulSoup(html, "html.parser")
    title_tag = main_soup.find("title")
    course_name = title_tag.get_text(strip=True) if title_tag else fallback_course_name
    calendar_events = []

    async with httpx.AsyncClient(
        follow_redirects=True,
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0 (compatible; Syntra/1.0)"},
    ) as client:
        try:
            response = await client.get(urljoin(base_url, "events_source.json"))
            if response.status_code == 200:
                data = response.json()
                if "eventSources" in data:
                    calendar_events = _parse_events_source_json(data)
        except Exception:
            pass

        if not calendar_events:
            calendar_events = parse_supported_calendar_soup(main_soup)

        if not calendar_events:
            candidate_urls = []
            seen_urls = set()

            def add_candidate(url: str) -> None:
                if url not in seen_urls:
                    seen_urls.add(url)
                    candidate_urls.append(url)

            for link in main_soup.find_all("a", href=True):
                href = link["href"]
                text = link.get_text(" ", strip=True)
                if CALENDAR_LINK_RE.search(href) or CALENDAR_LINK_RE.search(text):
                    add_candidate(urljoin(course_url, href))

            for path in _CALENDAR_CANDIDATES:
                add_candidate(urljoin(base_url, path))

            for candidate_url in candidate_urls:
                try:
                    response = await client.get(candidate_url)
                    if response.status_code != 200:
                        continue

                    calendar_soup = BeautifulSoup(response.text, "html.parser")
                    calendar_events = parse_supported_calendar_soup(calendar_soup)
                    if calendar_events:
                        candidate_title = calendar_soup.find("title")
                        if candidate_title:
                            course_name = candidate_title.get_text(strip=True)
                        break
                except Exception:
                    continue

    if not calendar_events:
        calendar_events = _html_fallback(main_soup, datetime.now().year)

    if not calendar_events:
        return None

    parsed_data = convert_calendar_events_to_unified(calendar_events, course_name, course_url)
    if not parsed_data["class_events"] and not parsed_data["assignments"]:
        return None

    return parsed_data


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

    prompt = f"""Extract ALL course events from this course page and return in UNIFIED FORMAT.

IMPORTANT: Extract ACTUAL CALENDAR DATES from the page, not URL fragments.
Only include events or assignments with explicit dates in YYYY-MM-DD format.
If an item only has a quarter code like 26sp, a day of week, or a recurring time, omit it.

Course: {course_name}
Text:
{text}

Return ONLY valid JSON (no markdown, no code blocks) with UnifiedClassEvent and UnifiedAssignment format:

For class_events (lectures, labs, sections, exams, etc.):
{{
  "event_name": "Lecture 1" or "Lab A" or "Midterm Exam",
  "event_type": "lecture|lab|section|discussion|exam|office_hours",
  "date": "YYYY-MM-DD",
  "start_time": "HH:MM" (24h format) or null,
  "end_time": "HH:MM" (24h format) or null,
  "location": "room name" or "Online" or null,
  "description": "brief description" or null,
  "course_name": "{course_name}",
  "source_url": "the course url"
}}

For assignments (homework, projects, quizzes, etc.):
{{
  "assignment_name": "HW1" or "Project 2",
  "assignment_type": "homework|project|exam|quiz|lab|reading",
  "due_date": "YYYY-MM-DD",
  "due_time": "HH:MM" (24h format) or null,
  "points": integer or null,
  "description": "full description",
  "submission_method": "Canvas|email|in-person" or null,
  "requirements": ["requirement 1", "requirement 2"],
  "is_individual": true or false,
  "is_group": true or false,
  "late_policy": "10% per day" or null,
  "course_name": "{course_name}",
  "source_url": "the course url"
}}

Return JSON with arrays of actual extracted items. Use empty arrays when no items are found.
Do not include placeholders, ellipses, comments, or trailing commas.
{{
  "course_name": "{course_name}",
  "class_events": [],
  "assignments": []
}}
"""

    try:
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                "http://localhost:11434/api/generate",
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
    """Convert Ollama's unified format to our models."""
    course_name = parsed_data.get("course_name", "Unknown Course")
    assignments = []
    class_events = []
    warnings = []

    # Create UnifiedAssignment objects from Ollama's output
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

            # Ensure required fields are set
            raw_assignment["source_url"] = course_url
            raw_assignment["course_name"] = raw_assignment.get("course_name", course_name)
            assignment = UnifiedAssignment(**raw_assignment)
            assignments.append(assignment)
        except Exception as e:
            warnings.append(
                f"Skipped assignment {raw_assignment.get('assignment_name', 'Unknown')}: {e}"
            )
            print(f"Error parsing assignment: {raw_assignment} - {e}")

    # Create UnifiedClassEvent objects from Ollama's output
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

            # Ensure required fields are set
            raw_event["source_url"] = course_url
            raw_event["course_name"] = raw_event.get("course_name", course_name)
            event = UnifiedClassEvent(**raw_event)
            class_events.append(event)
        except Exception as e:
            warnings.append(f"Skipped event {raw_event.get('event_name', 'Class Event')}: {e}")
            print(f"Error parsing event: {raw_event} - {e}")

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

    # 3. Prefer deterministic calendar parsing, then fall back to Ollama AI
    parsed_data = await parse_static_course_calendar(course_url, html, course_name)
    if parsed_data is None:
        parsed_data = await parse_with_ollama(html, course_name)

    # 4. Convert to unified format
    assignments, class_events, warnings = convert_to_unified_format(parsed_data, course_url)

    # 5. Deduplicate
    unique_assignments = deduplicate_assignments(assignments)
    unique_class_events = deduplicate_class_events(class_events)

    # 6. Convert to dict for response
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
