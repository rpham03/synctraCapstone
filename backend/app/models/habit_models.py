"""Domain models for Reclaim-style habit scheduling."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional


@dataclass(frozen=True)
class TimeRange:
    """Clock range within a day (minutes from midnight)."""

    start_minutes: int
    end_minutes: int

    def contains(self, start: int, end: int) -> bool:
        return self.start_minutes <= start and end <= self.end_minutes

    def center_minutes(self) -> float:
        return (self.start_minutes + self.end_minutes) / 2.0


@dataclass
class Habit:
    id: str
    user_id: str
    title: str
    duration_minutes: int
    frequency_per_week: int
    preferred_days: List[int]  # 0=Monday … 6=Sunday (Python weekday)
    preferred_time_ranges: Dict[int, List[TimeRange]]
    priority: int  # 1–10
    duration_max_minutes: int = 0  # 0 => same as duration_minutes
    is_active: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)


@dataclass(frozen=True)
class CalendarEvent:
    """Fixed calendar occupancy — always beats habits."""

    id: str
    title: str
    start: datetime
    end: datetime
    source: str = "calendar"


@dataclass
class HabitSession:
    """A scheduled habit occurrence (flexible — may move on conflict)."""

    id: str
    habit_id: str
    habit_title: str
    start: datetime
    end: datetime
    explanation: str
    score: float = 0.0


@dataclass(frozen=True)
class ScoredCandidate:
    habit_id: str
    start: datetime
    end: datetime
    score: float
    explanation: str


@dataclass(frozen=True)
class ScheduleDecision:
    session: HabitSession
    explanation: str
