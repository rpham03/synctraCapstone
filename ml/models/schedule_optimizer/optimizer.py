# Finds free time slots around fixed events and places flexible task blocks into them.
"""
Schedule Optimizer
------------------
Given a list of tasks with estimated durations and a set of fixed events,
find the best placement for flexible study/work blocks.

Approach: constraint-based greedy placement with ML-ranked time slots.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Tuple


@dataclass
class TimeSlot:
    start: datetime
    end: datetime

    @property
    def duration_minutes(self) -> int:
        return int((self.end - self.start).total_seconds() / 60)


def find_free_slots(
    fixed_events: List[Tuple[datetime, datetime]],
    window_start: datetime,
    window_end: datetime,
    min_slot_minutes: int = 30,
) -> List[TimeSlot]:
    """Return free time slots within [window_start, window_end]."""
    slots: List[TimeSlot] = []
    cursor = window_start

    for ev_start, ev_end in sorted(fixed_events):
        if cursor < ev_start:
            gap_minutes = int((ev_start - cursor).total_seconds() / 60)
            if gap_minutes >= min_slot_minutes:
                slots.append(TimeSlot(start=cursor, end=ev_start))
        cursor = max(cursor, ev_end)

    if cursor < window_end:
        gap_minutes = int((window_end - cursor).total_seconds() / 60)
        if gap_minutes >= min_slot_minutes:
            slots.append(TimeSlot(start=cursor, end=window_end))

    return slots
