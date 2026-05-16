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

router = APIRouter(tags=["course-import"])


class CourseImportResponse(BaseModel):
    """Response from course import."""
    course_url: str
    course_name: str
    assignments_imported: int
    class_events_imported: int
    total_imported: int
    warnings: list[str] = []


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

    prompt = f"""Extract ALL course events from this course page text.

For LECTURES, LABS, SECTIONS, EXAMS, etc., provide:
- event_name: e.g., "Lecture 1", "Lab A", "Midterm Exam"
- event_type: lecture, lab, section, discussion, exam, office_hours
- date: YYYY-MM-DD format
- start_time: HH:MM format (24h), or null if not specified
- end_time: HH:MM format (24h), or null if not specified
- location: room/building or "Online" or null
- description: brief description

For HOMEWORK, ASSIGNMENTS, PROJECTS, etc., provide:
- assignment_name: e.g., "HW1", "Project 2", "Midterm"
- assignment_type: homework, project, exam, quiz, lab, reading
- due_date: YYYY-MM-DD format
- due_time: HH:MM format (24h), or null if not specified
- points: integer or null
- description: brief description
- submission_method: Canvas, email, in-person, etc.
- requirements: list of requirements
- is_individual: true/false
- is_group: true/false
- late_policy: description or null

Course: {course_name}
Text:
{text}

Return ONLY valid JSON (no markdown, no code blocks) with this structure:
{{
  "course_name": "{course_name}",
  "class_events": [
    {{"event_name": "...", "event_type": "...", "date": "...", "start_time": "...", "end_time": "...", "location": "...", "description": "..."}},
    ...
  ],
  "assignments": [
    {{"assignment_name": "...", "assignment_type": "...", "due_date": "...", "due_time": "...", "points": null, "description": "...", "submission_method": null, "requirements": [], "is_individual": true, "is_group": false, "late_policy": null}},
    ...
  ]
}}
"""

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "mistral",
                    "prompt": prompt,
                    "stream": False,
                },
            )

        if response.status_code != 200:
            raise HTTPException(status_code=500, detail=f"Ollama error: {response.text}")

        result = response.json()
        response_text = result.get("response", "")

        # Extract JSON from response
        json_match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())

        raise HTTPException(status_code=500, detail="Could not parse Ollama response")

    except httpx.ConnectError:
        raise HTTPException(
            status_code=503,
            detail="Ollama server not running. Start with: ollama serve",
        )


def convert_to_unified_format(
    parsed_data: dict,
    course_url: str,
) -> tuple[list[UnifiedAssignment], list[UnifiedClassEvent]]:
    """Convert parsed data to unified format."""
    course_name = parsed_data.get("course_name", "Unknown Course")
    assignments = []
    class_events = []

    # Convert assignments
    for raw_assignment in parsed_data.get("assignments", []):
        try:
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
            print(f"Error converting assignment: {e}")

    # Convert class events
    for raw_event in parsed_data.get("class_events", []):
        try:
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
            print(f"Error converting event: {e}")

    return assignments, class_events


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
    assignments, class_events = convert_to_unified_format(parsed_data, course_url)

    # 5. Deduplicate
    unique_assignments = deduplicate_assignments(assignments)
    unique_class_events = deduplicate_class_events(class_events)

    return CourseImportResponse(
        course_url=course_url,
        course_name=parsed_data.get("course_name", course_name),
        assignments_imported=len(unique_assignments),
        class_events_imported=len(unique_class_events),
        total_imported=len(unique_assignments) + len(unique_class_events),
        warnings=[],
    )
