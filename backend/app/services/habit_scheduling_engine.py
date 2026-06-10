"""Places habit sessions into free calendar gaps with scored candidates."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Sequence, Tuple

from app.models.habit_models import CalendarEvent, Habit, HabitSession, ScoredCandidate
from app.services.habit_conflict_detection import (
    free_intervals_in_range,
    is_slot_free,
    occupied_from_events,
    occupied_with_sessions,
)
from app.services.habit_slot_scoring import score_candidate

Interval = Tuple[datetime, datetime]
SLOT_STEP_MINUTES = 15
HABIT_SPACING_MINUTES = 30


class HabitSchedulingEngine:
    """Analyze occupied time, generate candidates, score, and pack sessions."""

    def schedule_habits(
        self,
        habits: Sequence[Habit],
        calendar_events: Sequence[CalendarEvent],
        *,
        week_start: datetime,
        look_ahead_days: int = 7,
        day_start_hour: int = 7,
        day_end_hour: int = 23,
        existing_sessions: Sequence[HabitSession] | None = None,
    ) -> List[HabitSession]:
        """Schedule habit sessions, optionally preserving non-conflicting existing ones."""
        horizon_end = week_start + timedelta(days=look_ahead_days)
        return self._pack_all(
            habits,
            calendar_events,
            week_start=week_start,
            horizon_end=horizon_end,
            day_start_hour=day_start_hour,
            day_end_hour=day_end_hour,
            seed_sessions=list(existing_sessions or []),
        )

    def schedule_habits_fresh(
        self,
        habits: Sequence[Habit],
        calendar_events: Sequence[CalendarEvent],
        *,
        week_start: datetime,
        look_ahead_days: int = 7,
        day_start_hour: int = 7,
        day_end_hour: int = 23,
    ) -> List[HabitSession]:
        """Schedule all sessions from scratch (no retained habit sessions)."""
        return self._pack_all(
            habits,
            calendar_events,
            week_start=week_start,
            horizon_end=week_start + timedelta(days=look_ahead_days),
            day_start_hour=day_start_hour,
            day_end_hour=day_end_hour,
            seed_sessions=[],
        )

    def _pack_all(
        self,
        habits: Sequence[Habit],
        calendar_events: Sequence[CalendarEvent],
        *,
        week_start: datetime,
        horizon_end: datetime,
        day_start_hour: int,
        day_end_hour: int,
        seed_sessions: List[HabitSession],
    ) -> List[HabitSession]:
        sessions: List[HabitSession] = list(seed_sessions)
        day_load: Dict[int, int] = {}

        active = [h for h in habits if h.is_active]
        active.sort(key=lambda h: h.priority, reverse=True)

        for habit in active:
            already = self._count_habit_sessions(sessions, habit.id, week_start, horizon_end)
            needed = max(0, habit.frequency_per_week - already)
            placed = 0
            attempts = 0
            spread_days = self._spread_preferred_days(habit, week_start)
            habit_days_used: set[int] = set()
            while placed < needed and attempts < needed * 40:
                attempts += 1
                candidates = self._generate_candidates(
                    habit,
                    week_start=week_start,
                    horizon_end=horizon_end,
                    day_start_hour=day_start_hour,
                    day_end_hour=day_end_hour,
                    calendar_events=calendar_events,
                    sessions=sessions,
                )
                if not candidates:
                    break
                pool = candidates
                if spread_days:
                    target_day = next(
                        (day for day in spread_days if day not in habit_days_used),
                        None,
                    )
                    if target_day is not None:
                        day_pool = [c for c in candidates if c.start.weekday() == target_day]
                        if day_pool:
                            pool = day_pool
                week_count = self._count_habit_sessions(sessions, habit.id, week_start, horizon_end)
                scored = [
                    score_candidate(
                        habit,
                        c.start,
                        c.end,
                        existing_sessions=sessions,
                        day_session_counts=day_load,
                        week_session_count_for_habit=week_count,
                    )
                    for c in pool
                ]
                scored.sort(key=lambda c: (-c.score, c.start))
                best = scored[0]
                sessions.append(
                    HabitSession(
                        id=str(uuid.uuid4()),
                        habit_id=habit.id,
                        habit_title=habit.title,
                        start=best.start,
                        end=best.end,
                        explanation=best.explanation,
                        score=best.score,
                    )
                )
                day_load[best.start.weekday()] = day_load.get(best.start.weekday(), 0) + 1
                habit_days_used.add(best.start.weekday())
                placed += 1
        return sessions

    @staticmethod
    def _spread_preferred_days(habit: Habit, week_start: datetime) -> List[int]:
        """Order preferred days from the week anchor so sessions spread across the week."""
        if not habit.preferred_days:
            return []
        anchor = week_start.weekday()
        ordered: List[int] = []
        for offset in range(7):
            day = (anchor + offset) % 7
            if day in habit.preferred_days and day not in ordered:
                ordered.append(day)
        for day in sorted(habit.preferred_days):
            if day not in ordered:
                ordered.append(day)
        return ordered

    def _generate_candidates(
        self,
        habit: Habit,
        *,
        week_start: datetime,
        horizon_end: datetime,
        day_start_hour: int,
        day_end_hour: int,
        calendar_events: Sequence[CalendarEvent],
        sessions: Sequence[HabitSession],
    ) -> List[ScoredCandidate]:
        max_m = max(
            habit.duration_minutes,
            habit.duration_max_minutes or habit.duration_minutes,
        )
        min_m = habit.duration_minutes
        durations = [timedelta(minutes=max_m)]
        if max_m > min_m:
            durations.append(timedelta(minutes=min_m))
        occupied = occupied_with_sessions(
            calendar_events,
            sessions,
            habit_buffer_minutes=HABIT_SPACING_MINUTES,
        )
        candidates: List[ScoredCandidate] = []

        day = week_start.replace(hour=0, minute=0, second=0, microsecond=0)
        while day < horizon_end:
            weekday = day.weekday()
            if habit.preferred_days and weekday not in habit.preferred_days:
                day += timedelta(days=1)
                continue

            window_start = day.replace(hour=day_start_hour, minute=0)
            window_end = day.replace(hour=day_end_hour, minute=0)
            if window_end <= week_start:
                day += timedelta(days=1)
                continue
            if window_start < week_start:
                window_start = week_start

            time_ranges = habit.preferred_time_ranges.get(weekday)
            day_candidates: List[ScoredCandidate] = []
            for duration in durations:
                day_candidates.clear()
                if time_ranges:
                    for tr in time_ranges:
                        range_start = day.replace(hour=tr.start_minutes // 60, minute=tr.start_minutes % 60)
                        range_end = day.replace(hour=tr.end_minutes // 60, minute=tr.end_minutes % 60)
                        if tr.end_minutes <= tr.start_minutes:
                            range_end += timedelta(days=1)
                        day_candidates.extend(
                            self._slots_in_window(
                                range_start,
                                range_end,
                                duration,
                                occupied,
                                habit.id,
                            )
                        )
                    if not day_candidates:
                        day_candidates.extend(
                            self._slots_in_window(window_start, window_end, duration, occupied, habit.id)
                        )
                else:
                    day_candidates.extend(
                        self._slots_in_window(window_start, window_end, duration, occupied, habit.id)
                    )
                if day_candidates:
                    break
            candidates.extend(day_candidates)
            day += timedelta(days=1)

        return candidates

    def _slots_in_window(
        self,
        window_start: datetime,
        window_end: datetime,
        duration: timedelta,
        occupied: Sequence[Interval],
        habit_id: str,
    ) -> List[ScoredCandidate]:
        out: List[ScoredCandidate] = []
        for gap_start, gap_end in free_intervals_in_range(
            occupied, window_start, window_end, min_minutes=int(duration.total_seconds() // 60)
        ):
            cursor = gap_start
            while cursor + duration <= gap_end:
                end = cursor + duration
                if is_slot_free(occupied, cursor, end):
                    out.append(
                        ScoredCandidate(
                            habit_id=habit_id,
                            start=cursor,
                            end=end,
                            score=0.0,
                            explanation="",
                        )
                    )
                cursor += timedelta(minutes=SLOT_STEP_MINUTES)
        return out

    @staticmethod
    def _count_habit_sessions(
        sessions: Sequence[HabitSession],
        habit_id: str,
        week_start: datetime,
        horizon_end: datetime,
    ) -> int:
        return sum(
            1
            for s in sessions
            if s.habit_id == habit_id and s.start >= week_start and s.start < horizon_end
        )
