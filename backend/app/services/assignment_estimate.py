# Generous assignment work-time estimates for below-average students (not experts).
"""Shared homework duration estimates used by Canvas, course import, and chat."""
from __future__ import annotations

import re

# Round to 30-minute blocks; allow up to 16h for large projects.
MIN_ESTIMATE_MINUTES = 60
MAX_ESTIMATE_MINUTES = 960
ROUND_BLOCK_MINUTES = 30

# Focused work time for a struggling / below-average student (includes breaks, confusion, revision).
BASE_MINUTES_BY_TYPE: dict[str, int] = {
    "reading": 120,
    "quiz": 120,
    "homework": 300,
    "lab": 240,
    "exam": 360,
    "project": 600,
}
DEFAULT_ASSIGNMENT_MINUTES = 300

# Shown in LLM prompts for website/course-import parsing.
ESTIMATE_AI_GUIDANCE = """- For each assignment, set estimated_minutes for a below-average student who
  needs extra time (not a fast expert). Include reading the prompt, setup, false starts,
  debugging, asking for help, and revision. Prefer longer estimates over short ones.
  Use 30-minute increments between 60 and 960 minutes."""


def infer_assignment_type(title: str) -> str:
    """Infer assignment type from a title."""
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


def round_estimate_minutes(minutes: int) -> int:
    """Round to student-friendly blocks with generous floor/ceiling."""
    block = ROUND_BLOCK_MINUTES
    rounded = int(round(minutes / block) * block)
    return max(MIN_ESTIMATE_MINUTES, min(MAX_ESTIMATE_MINUTES, rounded))


def coerce_estimated_minutes(
    value: object,
    *,
    assignment_type: str | None = None,
) -> int | None:
    """Accept LLM/user estimate values; enforce type floor for below-average students."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        minutes = int(value)
    elif isinstance(value, str) and value.strip().isdigit():
        minutes = int(value.strip())
    else:
        return None
    if minutes <= 0:
        return None

    minutes = round_estimate_minutes(minutes)
    if assignment_type:
        floor = BASE_MINUTES_BY_TYPE.get(assignment_type, DEFAULT_ASSIGNMENT_MINUTES)
        minutes = max(minutes, floor)
    return round_estimate_minutes(minutes)


def estimate_assignment_minutes(
    assignment_name: str,
    assignment_type: str | None = None,
    description: str = "",
    requirements: list[str] | None = None,
    points: int | float | None = None,
) -> int:
    """Estimate focused work time for a below-average student."""
    assignment_type = assignment_type or infer_assignment_type(assignment_name)
    text = " ".join(
        [
            assignment_name,
            assignment_type,
            description or "",
            " ".join(requirements or []),
        ]
    ).lower()

    minutes = BASE_MINUTES_BY_TYPE.get(assignment_type, DEFAULT_ASSIGNMENT_MINUTES)

    if isinstance(points, (int, float)) and points > 0:
        # ~6 minutes per point, capped high — struggling students take longer per point.
        minutes = max(minutes, min(MAX_ESTIMATE_MINUTES, int(points * 6)))

    keyword_adjustments = [
        (r"\b(final|capstone|milestone|portfolio)\b", 300),
        (r"\b(project|programming|implementation|code|coding|build|debug)\b", 180),
        (r"\b(report|paper|write[- ]?up|essay|reflection|revise|revision)\b", 150),
        (r"\b(proof|problem set|pset|theory|analysis)\b", 150),
        (r"\b(machine learning|dataset|model|experiment|evaluation)\b", 150),
        (r"\b(checkpoint|proposal|survey)\b", 30),
        (r"\b(extra credit|optional)\b", -30),
    ]
    for pattern, delta in keyword_adjustments:
        if re.search(pattern, text):
            minutes += delta

    req_count = len(requirements or [])
    if req_count > 1:
        minutes += min(240, (req_count - 1) * 60)

    return round_estimate_minutes(minutes)


def estimate_canvas_assignment_minutes(assignment: dict) -> int:
    """Canvas API assignment dict → generous below-average student estimate."""
    title = (assignment.get("name") or "Assignment").strip()
    description = assignment.get("description") or ""
    if isinstance(description, str):
        # Strip simple HTML tags from Canvas descriptions.
        description = re.sub(r"<[^>]+>", " ", description)
    points = assignment.get("points_possible")
    pts: int | float | None = None
    if isinstance(points, (int, float)) and points > 0:
        pts = points
    return estimate_assignment_minutes(
        title,
        infer_assignment_type(title),
        description=description if isinstance(description, str) else "",
        points=pts,
    )
