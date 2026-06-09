"""Detect overlaps between fixed calendar events and flexible habit sessions."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Iterable, List, Sequence, Tuple

from app.models.habit_models import CalendarEvent, HabitSession


Interval = Tuple[datetime, datetime]


def _overlaps(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    return a_start < b_end and b_start < a_end


def merge_intervals(intervals: List[Interval]) -> List[Interval]:
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda x: x[0])
    merged: List[Interval] = [ordered[0]]
    for start, end in ordered[1:]:
        ps, pe = merged[-1]
        if start <= pe:
            merged[-1] = (ps, max(pe, end))
        else:
            merged.append((start, end))
    return merged


def occupied_from_events(events: Sequence[CalendarEvent]) -> List[Interval]:
    return merge_intervals([(e.start, e.end) for e in events])


def occupied_with_sessions(
    events: Sequence[CalendarEvent],
    sessions: Sequence[HabitSession],
    *,
    habit_buffer_minutes: int = 0,
) -> List[Interval]:
    """Build occupied intervals; optionally pad habit sessions for spacing."""
    raw = [(e.start, e.end) for e in events]
    buffer = timedelta(minutes=max(0, habit_buffer_minutes))
    for s in sessions:
        raw.append((s.start - buffer, s.end + buffer))
    return merge_intervals(raw)


def find_conflicting_sessions(
    sessions: Sequence[HabitSession],
    blocking_start: datetime,
    blocking_end: datetime,
) -> List[HabitSession]:
    """Sessions that overlap a new fixed event (habits yield)."""
    return [
        s
        for s in sessions
        if _overlaps(s.start, s.end, blocking_start, blocking_end)
    ]


def is_slot_free(
    occupied: Sequence[Interval],
    start: datetime,
    end: datetime,
) -> bool:
    for busy_start, busy_end in occupied:
        if _overlaps(start, end, busy_start, busy_end):
            return False
    return True


def free_intervals_in_range(
    occupied: Sequence[Interval],
    range_start: datetime,
    range_end: datetime,
    *,
    min_minutes: int = 15,
) -> List[Interval]:
    """Return gaps inside [range_start, range_end] not covered by occupied."""
    if range_end <= range_start:
        return []
    relevant = [
        (max(s, range_start), min(e, range_end))
        for s, e in occupied
        if s < range_end and e > range_start
    ]
    merged = merge_intervals(relevant)
    free: List[Interval] = []
    cursor = range_start
    for busy_start, busy_end in merged:
        if busy_start > cursor:
            gap = (cursor, busy_start)
            if (gap[1] - gap[0]).total_seconds() >= min_minutes * 60:
                free.append(gap)
        cursor = max(cursor, busy_end)
    if cursor < range_end:
        gap = (cursor, range_end)
        if (gap[1] - gap[0]).total_seconds() >= min_minutes * 60:
            free.append(gap)
    return free
