"""Score candidate habit placements for the scheduling engine."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, List, Sequence, Tuple

from app.models.habit_models import Habit, HabitSession, ScoredCandidate, TimeRange

_DAY_NAMES = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _minutes_since_midnight(dt: datetime) -> int:
    return dt.hour * 60 + dt.minute


def _format_time(dt: datetime) -> str:
    hour = dt.strftime("%I").lstrip("0") or "12"
    return f"{hour} {dt.strftime('%p')}"


def _period_label(minutes: int) -> str:
    if minutes < 12 * 60:
        return "morning"
    if minutes < 17 * 60:
        return "afternoon"
    if minutes < 21 * 60:
        return "evening"
    return "night"


def score_candidate(
    habit: Habit,
    start: datetime,
    end: datetime,
    *,
    existing_sessions: Sequence[HabitSession],
    day_session_counts: Dict[int, int],
    week_session_count_for_habit: int,
) -> ScoredCandidate:
    """Higher is better. Builds a human-readable explanation."""
    score = 0.0
    reasons: List[str] = []

    weekday = start.weekday()
    start_min = _minutes_since_midnight(start)
    end_min = _minutes_since_midnight(end)

    # Preferred day (strong signal)
    if weekday in habit.preferred_days:
        score += 35.0
        reasons.append(f"matched preferred { _DAY_NAMES[weekday] }")
    else:
        score -= 15.0

    # Preferred time window
    day_ranges: List[TimeRange] = habit.preferred_time_ranges.get(weekday, [])
    if not day_ranges:
        for day in habit.preferred_days:
            day_ranges.extend(habit.preferred_time_ranges.get(day, []))

    time_matched = False
    best_center_delta = 9999.0
    for tr in day_ranges:
        if tr.contains(start_min, end_min):
            time_matched = True
            center_delta = abs(start_min - tr.center_minutes())
            best_center_delta = min(best_center_delta, center_delta)
    if time_matched:
        score += 30.0 - min(15.0, best_center_delta / 20.0)
        period = _period_label(start_min)
        reasons.append(f"matched preferred {period} availability")
    elif day_ranges:
        score -= 10.0

    # Avoid stacking different habits at the same time
    for other in existing_sessions:
        if other.habit_id == habit.id:
            continue
        if other.start < end and start < other.end:
            score -= 200.0
            reasons.append("avoided overlap with another habit")
            break

    # Spacing between sessions of the same habit this week
    habit_sessions = [s for s in existing_sessions if s.habit_id == habit.id]
    if habit_sessions:
        gaps_hours: List[float] = []
        for s in habit_sessions:
            if s.end <= start:
                gaps_hours.append((start - s.end).total_seconds() / 3600)
            elif s.start >= end:
                gaps_hours.append((s.start - end).total_seconds() / 3600)
        if gaps_hours:
            min_gap = min(gaps_hours)
            if min_gap >= 24:
                score += 20.0
                reasons.append("maintained spacing from previous sessions")
            elif min_gap >= 12:
                score += 10.0
            else:
                score -= 8.0
    elif week_session_count_for_habit == 0:
        score += 5.0

    # Priority multiplier (1–10)
    priority_factor = 0.5 + (habit.priority / 10.0)
    score *= priority_factor
    if habit.priority >= 8:
        reasons.append("high-priority habit")

    # Calendar load balancing — prefer days with fewer sessions overall
    load = day_session_counts.get(weekday, 0)
    score += max(0.0, 18.0 - load * 4.0)
    if load == 0:
        reasons.append("balanced calendar load on a lighter day")

    explanation = _build_explanation(start, reasons)
    return ScoredCandidate(
        habit_id=habit.id,
        start=start,
        end=end,
        score=round(score, 2),
        explanation=explanation,
    )


def _build_explanation(start: datetime, reasons: List[str]) -> str:
    day = _DAY_NAMES[start.weekday()]
    time_label = _format_time(start)
    if not reasons:
        return f"Scheduled on {day} {time_label} in the next available slot."
    joined = ", ".join(reasons[:3])
    return f"Scheduled on {day} {time_label} because it {joined}."
