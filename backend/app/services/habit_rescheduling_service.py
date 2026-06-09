"""Reschedule habits when new fixed events create conflicts."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Sequence

from app.models.habit_models import CalendarEvent, Habit, HabitSession
from app.services.habit_conflict_detection import find_conflicting_sessions
from app.services.habit_scheduling_engine import HabitSchedulingEngine


class HabitReschedulingService:
    def __init__(self, engine: HabitSchedulingEngine | None = None) -> None:
        self._engine = engine or HabitSchedulingEngine()

    def reschedule_after_new_event(
        self,
        *,
        habits: Sequence[Habit],
        calendar_events: Sequence[CalendarEvent],
        current_sessions: Sequence[HabitSession],
        new_event: CalendarEvent,
        week_start: datetime,
        look_ahead_days: int = 7,
    ) -> tuple[List[HabitSession], List[dict]]:
        """
        Remove habit sessions conflicting with the new event, then refill affected habits.
        Returns (updated_sessions, change_log).
        """
        horizon_end = week_start + timedelta(days=look_ahead_days)
        conflicts = find_conflicting_sessions(
            current_sessions, new_event.start, new_event.end
        )
        if not conflicts:
            return list(current_sessions), []

        conflict_ids = {s.id for s in conflicts}
        affected_habit_ids = {s.habit_id for s in conflicts}
        retained = [s for s in current_sessions if s.id not in conflict_ids]

        all_events = list(calendar_events) + [new_event]
        affected_habits = [h for h in habits if h.id in affected_habit_ids and h.is_active]

        refilled: List[HabitSession] = []
        change_log: List[dict] = []

        for habit in affected_habits:
            already = sum(
                1
                for s in retained
                if s.habit_id == habit.id and week_start <= s.start < horizon_end
            )
            missing = max(0, habit.frequency_per_week - already)
            if missing == 0:
                continue

            # Temporarily treat retained + calendar as occupied; schedule missing slots
            partial = self._engine.schedule_habits(
                [habit],
                all_events,
                week_start=week_start,
                look_ahead_days=look_ahead_days,
                existing_sessions=retained + refilled,
            )
            new_for_habit = [s for s in partial if s.habit_id == habit.id][:missing]
            for s in new_for_habit:
                refilled.append(s)
                change_log.append(
                    {
                        "habit_id": habit.id,
                        "habit_title": habit.title,
                        "action": "rescheduled",
                        "new_start": s.start.isoformat(),
                        "new_end": s.end.isoformat(),
                        "explanation": s.explanation,
                        "reason": f"Moved to avoid conflict with '{new_event.title}'.",
                    }
                )

        for s in conflicts:
            change_log.append(
                {
                    "habit_id": s.habit_id,
                    "habit_title": s.habit_title,
                    "action": "displaced",
                    "old_start": s.start.isoformat(),
                    "old_end": s.end.isoformat(),
                    "reason": f"Conflict with new event '{new_event.title}'.",
                }
            )

        return retained + refilled, change_log
