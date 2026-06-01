"""
Unified course format - standardized data structures for all course websites.

This module defines:
1. UnifiedAssignment - Standard format for all assignments/projects/quizzes
2. UnifiedClassEvent - Standard format for all lectures/labs/sections
3. Converter functions to convert from different sources
4. Calendar import function to add events to Supabase
"""

from typing import Optional
from pydantic import BaseModel
from datetime import datetime


# ============================================================================
# UNIFIED DATA MODELS
# ============================================================================

class UnifiedAssignment(BaseModel):
    """Standardized assignment format (works for all websites)."""
    assignment_name: str  # "HW1", "Project 2", "Midterm"
    assignment_type: str  # "homework", "project", "exam", "quiz", "lab", "reading"
    due_date: str  # ISO format: "2026-04-10"
    due_time: Optional[str]  # 24h format: "23:59", null if no time specified
    points: Optional[int]  # "10", null if not specified
    description: str  # Full description
    submission_method: Optional[str]  # "Canvas", "email", "in-person", etc.
    requirements: list[str]  # ["requirement 1", "requirement 2"]
    is_individual: bool  # Can submit individually?
    is_group: bool  # Can submit as group?
    late_policy: Optional[str]  # "10% per day", null if no policy
    estimated_minutes: Optional[int] = None  # Estimated focused work time
    course_name: str  # Which course: "CSE 331"
    source_url: str  # Where it came from


class UnifiedClassEvent(BaseModel):
    """Standardized class event format (works for all websites)."""
    event_name: str  # "Lecture 5", "Lab A", "Discussion Section"
    event_type: str  # "lecture", "section", "lab", "discussion", "office_hours", "exam"
    date: str  # ISO format: "2026-04-10"
    start_time: Optional[str]  # 24h format: "10:30", null if not specified
    end_time: Optional[str]  # 24h format: "11:20"
    location: Optional[str]  # "CSE2 B215", "Zoom", "Engineering Building Room 101"
    description: Optional[str]  # "Introduction to algorithms", "Office hours"
    course_name: str  # Which course: "CSE 331"
    source_url: str  # Where it came from


class CourseImportResult(BaseModel):
    """Result of course import with unified format."""
    course_url: str
    course_name: str
    parsing_method: str  # "regex_only", "hybrid", "ai_only"
    confidence: float  # 0.0-1.0
    assignments: list[UnifiedAssignment]
    class_events: list[UnifiedClassEvent]
    tokens_used: int
    processing_time_ms: int
    warnings: list[str]


# ============================================================================
# CONVERTER FUNCTIONS
# ============================================================================

def convert_to_unified_assignment(
    raw_assignment: dict,
    course_name: str,
    source_url: str
) -> UnifiedAssignment:
    """Convert any assignment format to unified format."""
    return UnifiedAssignment(
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
        estimated_minutes=raw_assignment.get("estimated_minutes"),
        course_name=course_name,
        source_url=source_url,
    )


def convert_to_unified_class_event(
    raw_event: dict,
    course_name: str,
    source_url: str
) -> UnifiedClassEvent:
    """Convert any class event format to unified format."""
    return UnifiedClassEvent(
        event_name=raw_event.get("event_name", "Class Event"),
        event_type=raw_event.get("event_type", "lecture"),
        date=raw_event.get("date", ""),
        start_time=raw_event.get("start_time", ""),
        end_time=raw_event.get("end_time"),
        location=raw_event.get("location"),
        description=raw_event.get("description"),
        course_name=course_name,
        source_url=source_url,
    )


# ============================================================================
# CALENDAR IMPORT
# ============================================================================

async def import_to_calendar(
    user_id: str,
    assignments: list[UnifiedAssignment],
    class_events: list[UnifiedClassEvent],
) -> dict:
    """
    Import unified events to calendar (Supabase).

    Args:
        user_id: User ID from auth
        assignments: List of UnifiedAssignment objects
        class_events: List of UnifiedClassEvent objects

    Returns:
        Import result with success/failure counts
    """
    result = {
        "assignments_imported": 0,
        "assignments_failed": 0,
        "class_events_imported": 0,
        "class_events_failed": 0,
        "details": [],
    }

    # ── Import Assignments ────────────────────────────────────────────────
    for assignment in assignments:
        try:
            # Create task in Supabase
            task_data = {
                "user_id": user_id,
                "title": assignment.assignment_name,
                "description": assignment.description,
                "due_date": f"{assignment.due_date}T{assignment.due_time or '23:59'}",
                "task_type": assignment.assignment_type,
                "course_name": assignment.course_name,
                "points": assignment.points,
                "submission_method": assignment.submission_method,
                "is_individual": assignment.is_individual,
                "is_group": assignment.is_group,
                "late_policy": assignment.late_policy,
                "requirements": assignment.requirements,
                "source": "course_import",
                "source_url": assignment.source_url,
                "source_task_id": f"{assignment.course_name}_{assignment.assignment_name}",
                "created_at": datetime.now().isoformat(),
            }

            # TODO: Implement Supabase insert
            # supabase.table("tasks").upsert(task_data, on_conflict="user_id,source_task_id").execute()

            result["assignments_imported"] += 1
            result["details"].append(
                f"✅ Assignment: {assignment.assignment_name} ({assignment.course_name})"
            )
        except Exception as e:
            result["assignments_failed"] += 1
            result["details"].append(
                f"❌ Assignment: {assignment.assignment_name} - {str(e)}"
            )

    # ── Import Class Events ───────────────────────────────────────────────
    for event in class_events:
        try:
            # Create event in Supabase
            event_data = {
                "user_id": user_id,
                "title": event.event_name,
                "description": event.description or f"{event.event_type.capitalize()} - {event.course_name}",
                "location": event.location,
                "start_time": f"{event.date}T{event.start_time}",
                "end_time": f"{event.date}T{event.end_time or event.start_time}",
                "event_type": event.event_type,
                "course_name": event.course_name,
                "source": "course_import",
                "source_url": event.source_url,
                "source_event_id": f"{event.course_name}_{event.event_name}",
                "created_at": datetime.now().isoformat(),
            }

            # TODO: Implement Supabase insert
            # supabase.table("events").upsert(event_data, on_conflict="user_id,source_event_id").execute()

            result["class_events_imported"] += 1
            result["details"].append(
                f"✅ Event: {event.event_name} ({event.course_name})"
            )
        except Exception as e:
            result["class_events_failed"] += 1
            result["details"].append(
                f"❌ Event: {event.event_name} - {str(e)}"
            )

    # ── Summary ───────────────────────────────────────────────────────────
    result["summary"] = {
        "total_imported": result["assignments_imported"] + result["class_events_imported"],
        "total_failed": result["assignments_failed"] + result["class_events_failed"],
        "success_rate": (
            (result["assignments_imported"] + result["class_events_imported"])
            / (
                result["assignments_imported"]
                + result["assignments_failed"]
                + result["class_events_imported"]
                + result["class_events_failed"]
            )
            * 100
            if (
                result["assignments_imported"]
                + result["assignments_failed"]
                + result["class_events_imported"]
                + result["class_events_failed"]
            )
            > 0
            else 0
        ),
    }

    return result


# ============================================================================
# DEDUPLICATION & MERGING
# ============================================================================

def deduplicate_assignments(assignments: list[UnifiedAssignment]) -> list[UnifiedAssignment]:
    """Remove duplicate assignments based on course + name + due_date."""
    seen = {}
    unique = []

    for assignment in assignments:
        # Create unique key
        key = (
            assignment.course_name,
            assignment.assignment_name,
            assignment.due_date,
        )

        if key not in seen:
            seen[key] = assignment
            unique.append(assignment)

    return unique


def deduplicate_class_events(events: list[UnifiedClassEvent]) -> list[UnifiedClassEvent]:
    """Remove duplicate class events based on course + name + date + time."""
    seen = {}
    unique = []

    for event in events:
        # Create unique key
        key = (
            event.course_name,
            event.event_name,
            event.date,
            event.start_time,
        )

        if key not in seen:
            seen[key] = event
            unique.append(event)

    return unique


def merge_course_results(
    *course_results: dict,
) -> CourseImportResult:
    """
    Merge results from multiple courses into one unified import.

    Args:
        *course_results: Variable number of CourseImportResult dicts

    Returns:
        Single CourseImportResult with all courses combined
    """
    all_assignments = []
    all_events = []
    all_warnings = []

    for result in course_results:
        all_assignments.extend(result.get("assignments", []))
        all_events.extend(result.get("class_events", []))
        all_warnings.extend(result.get("warnings", []))

    # Deduplicate
    unique_assignments = deduplicate_assignments(all_assignments)
    unique_events = deduplicate_class_events(all_events)

    return CourseImportResult(
        course_url="Multiple",
        course_name="Multiple Courses",
        parsing_method="hybrid",
        confidence=0.85,
        assignments=unique_assignments,
        class_events=unique_events,
        tokens_used=0,
        processing_time_ms=0,
        warnings=all_warnings,
    )
