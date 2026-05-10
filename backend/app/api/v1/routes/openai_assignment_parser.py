"""
Assignment parser using OpenAI's ChatGPT API instead of Claude.

Compatible with hybrid_parser.py for drop-in replacement.
"""

import json
from datetime import datetime
from typing import Optional
from pydantic import BaseModel
from openai import OpenAI

# Initialize OpenAI client
client = OpenAI()  # Uses OPENAI_API_KEY env variable


class AssignmentDetail(BaseModel):
    """Structured assignment data extracted by ChatGPT."""
    assignment_name: str
    assignment_type: str  # "homework", "project", "exam", "quiz", "lab", "reading"
    due_date: str  # "2026-04-07" (ISO format)
    due_time: Optional[str]  # "23:59" (24h format)
    description: str
    submission_method: Optional[str]  # "Canvas", "In-person", etc.
    points: Optional[int]
    requirements: list[str]
    is_individual: bool
    is_group: bool
    late_policy: Optional[str]


class ClassEvent(BaseModel):
    """Structured class/meeting event extracted by ChatGPT."""
    event_name: str
    event_type: str  # "lecture", "section", "lab", "discussion", "office_hours"
    date: str  # "2026-04-07" (ISO)
    start_time: str  # "10:30" (24h)
    end_time: Optional[str]  # "11:20" (24h)
    location: Optional[str]
    description: Optional[str]


class ParsedEventCollection(BaseModel):
    """Collection of all parsed events from course text."""
    assignments: list[AssignmentDetail]
    class_events: list[ClassEvent]
    warnings: list[str]


def parse_course_events_with_chatgpt(
    raw_text: str,
    course_name: str = "Unknown Course",
    model: str = "gpt-4o-mini"  # Cheaper than gpt-4o
) -> ParsedEventCollection:
    """
    Use OpenAI's ChatGPT to intelligently parse assignment and class event details.

    Args:
        raw_text: Raw extracted text from course website
        course_name: Name of the course for context
        model: OpenAI model to use (gpt-4o-mini is cheaper)

    Returns:
        ParsedEventCollection with structured assignments and events
    """

    prompt = f"""You are an expert at parsing course assignment and class schedules from messy website text.

COURSE: {course_name}

RAW TEXT FROM COURSE WEBSITE:
{raw_text}

Please analyze this text and extract ALL assignments and class events.

For EACH ASSIGNMENT found, extract:
- assignment_name: The specific assignment (e.g., "HW1", "Project 2")
- assignment_type: Type from [homework, project, exam, reading, lab, quiz, essay, presentation]
- due_date: ISO format (YYYY-MM-DD). Use context clues like "next Friday"
- due_time: Time in 24h format (HH:MM). If not specified, null
- description: Full description
- submission_method: Where to submit (Canvas, email, in-person, etc.)
- points: Points if specified
- requirements: List of specific requirements
- is_individual: true if individual submission required
- is_group: true if group submission allowed
- late_policy: Penalty for late submission if specified

For EACH CLASS EVENT found, extract:
- event_name: Name like "Lecture 5", "Section A", "Lab"
- event_type: Type from [lecture, section, lab, discussion, office_hours, exam]
- date: ISO format (YYYY-MM-DD)
- start_time: Time in 24h format (HH:MM)
- end_time: Time in 24h format if available
- location: Room, building, Zoom link, etc.
- description: What will be covered

IMPORTANT:
1. Separate DIFFERENT assignments even if mentioned together
2. Separate CLASS TIMES from DUE TIMES
3. Calculate actual dates from relative dates (today is {datetime.now().strftime('%Y-%m-%d')})
4. If ambiguous, include a warning
5. Return ONLY valid JSON

{{
  "assignments": [
    {{
      "assignment_name": "HW1",
      "assignment_type": "homework",
      "due_date": "2026-04-07",
      "due_time": "23:59",
      "description": "...",
      "submission_method": "Canvas",
      "points": 10,
      "requirements": ["..."],
      "is_individual": true,
      "is_group": false,
      "late_policy": "..."
    }}
  ],
  "class_events": [
    {{
      "event_name": "Lecture 1",
      "event_type": "lecture",
      "date": "2026-04-01",
      "start_time": "10:30",
      "end_time": "11:20",
      "location": "CSE2 B215",
      "description": "Introduction to algorithms"
    }}
  ],
  "warnings": ["any ambiguities"]
}}
"""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,  # Low temperature for consistent parsing
            response_format={"type": "json_object"}  # Enforce JSON output
        )

        response_text = response.choices[0].message.content

        # Parse JSON
        try:
            data = json.loads(response_text)
        except json.JSONDecodeError as e:
            return ParsedEventCollection(
                assignments=[],
                class_events=[],
                warnings=[f"Failed to parse ChatGPT response: {e}"]
            )

        # Convert to models
        assignments = [
            AssignmentDetail(**a) for a in data.get("assignments", [])
        ]
        class_events = [
            ClassEvent(**c) for c in data.get("class_events", [])
        ]
        warnings = data.get("warnings", [])

        return ParsedEventCollection(
            assignments=assignments,
            class_events=class_events,
            warnings=warnings
        )

    except Exception as e:
        return ParsedEventCollection(
            assignments=[],
            class_events=[],
            warnings=[f"Error calling OpenAI API: {str(e)}"]
        )


def format_assignment_for_display(assignment: AssignmentDetail) -> str:
    """Format assignment for calendar display."""
    output = f"\n📋 {assignment.assignment_name.upper()}"
    output += f"\n   Type: {assignment.assignment_type.capitalize()}"
    output += f"\n   Due: {assignment.due_date} at {assignment.due_time or 'TBD'}"

    if assignment.points:
        output += f"\n   Points: {assignment.points}"

    if assignment.submission_method:
        output += f"\n   Submit: {assignment.submission_method}"

    if assignment.requirements:
        output += "\n   Requirements:"
        for req in assignment.requirements:
            output += f"\n     • {req}"

    if assignment.late_policy:
        output += f"\n   Late Policy: {assignment.late_policy}"

    return output


def format_event_for_display(event: ClassEvent) -> str:
    """Format class event for calendar display."""
    output = f"\n🎓 {event.event_name.upper()}"
    output += f"\n   Type: {event.event_type.capitalize()}"
    output += f"\n   Date: {event.date}"
    output += f"\n   Time: {event.start_time}"

    if event.end_time:
        output += f" - {event.end_time}"

    if event.location:
        output += f"\n   Location: {event.location}"

    if event.description:
        output += f"\n   Topic: {event.description}"

    return output


def add_to_calendar(user_id: str, parsed_events: ParsedEventCollection, course_name: str) -> dict:
    """
    User-defined function to add parsed events to calendar (Supabase).
    Same interface as Claude version for drop-in replacement.
    """
    results = {
        "assignments_added": 0,
        "events_added": 0,
        "warnings": parsed_events.warnings,
        "details": []
    }

    # TODO: Replace with actual Supabase client calls

    for assignment in parsed_events.assignments:
        try:
            task_data = {
                "user_id": user_id,
                "title": assignment.assignment_name,
                "description": assignment.description,
                "due_date": f"{assignment.due_date}T{assignment.due_time or '23:59'}",
                "task_type": assignment.assignment_type,
                "course_name": course_name,
                "source": "course_import",
                "source_task_id": f"{course_name}_{assignment.assignment_name}",
            }
            # supabase.table("tasks").insert(task_data).execute()
            results["assignments_added"] += 1
            results["details"].append(f"✅ Added: {assignment.assignment_name}")
        except Exception as e:
            results["details"].append(f"❌ Failed {assignment.assignment_name}: {str(e)}")

    for event in parsed_events.class_events:
        try:
            event_data = {
                "user_id": user_id,
                "title": event.event_name,
                "description": event.description or f"{event.event_type} - {course_name}",
                "location": event.location,
                "start_time": f"{event.date}T{event.start_time}",
                "end_time": f"{event.date}T{event.end_time or event.start_time}",
                "source": "course_import",
                "source_event_id": f"{course_name}_{event.event_name}",
            }
            # supabase.table("events").insert(event_data).execute()
            results["events_added"] += 1
            results["details"].append(f"✅ Added: {event.event_name}")
        except Exception as e:
            results["details"].append(f"❌ Failed {event.event_name}: {str(e)}")

    return results
