"""Facade for habit CRUD and scheduling operations."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import List, Optional, Sequence

from app.models.habit_models import CalendarEvent, Habit, HabitSession
from app.services.habit_repository import HabitRepository
from app.services.habit_rescheduling_service import HabitReschedulingService
from app.services.habit_scheduling_engine import HabitSchedulingEngine


def _monday_of(dt: datetime) -> datetime:
    base = dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return base - timedelta(days=base.weekday())


class HabitService:
    def __init__(
        self,
        repository: HabitRepository | None = None,
        engine: HabitSchedulingEngine | None = None,
        rescheduler: HabitReschedulingService | None = None,
    ) -> None:
        self._repo = repository or HabitRepository()
        self._engine = engine or HabitSchedulingEngine()
        self._rescheduler = rescheduler or HabitReschedulingService(self._engine)

    # ── CRUD ─────────────────────────────────────────────────────────────

    def list_habits(self, user_id: str) -> List[Habit]:
        return self._repo.list_for_user(user_id)

    def get_habit(self, user_id: str, habit_id: str) -> Optional[Habit]:
        return self._repo.get(user_id, habit_id)

    def create_habit(self, user_id: str, payload: dict) -> Habit:
        return self._repo.create(user_id, payload)

    def update_habit(self, user_id: str, habit_id: str, payload: dict) -> Optional[Habit]:
        return self._repo.update(user_id, habit_id, payload)

    def delete_habit(self, user_id: str, habit_id: str) -> bool:
        return self._repo.delete(user_id, habit_id)

    # ── Scheduling ───────────────────────────────────────────────────────

    def schedule_week(
        self,
        user_id: str,
        calendar_events: Sequence[CalendarEvent],
        *,
        week_start: datetime | None = None,
        look_ahead_days: int = 7,
    ) -> dict:
        habits = self._repo.list_for_user(user_id)
        week_start = week_start or _monday_of(datetime.utcnow())
        sessions = self._engine.schedule_habits_fresh(
            habits,
            calendar_events,
            week_start=week_start,
            look_ahead_days=look_ahead_days,
        )
        return {
            "week_start": week_start.isoformat(),
            "sessions": [_session_to_dict(s) for s in sessions],
            "decisions": [
                {"session_id": s.id, "habit_id": s.habit_id, "explanation": s.explanation}
                for s in sessions
            ],
        }

    def reschedule_for_new_event(
        self,
        user_id: str,
        calendar_events: Sequence[CalendarEvent],
        current_sessions: Sequence[HabitSession],
        new_event: CalendarEvent,
        *,
        week_start: datetime | None = None,
        look_ahead_days: int = 7,
    ) -> dict:
        habits = self._repo.list_for_user(user_id)
        week_start = week_start or _monday_of(datetime.utcnow())
        updated, log = self._rescheduler.reschedule_after_new_event(
            habits=habits,
            calendar_events=calendar_events,
            current_sessions=current_sessions,
            new_event=new_event,
            week_start=week_start,
            look_ahead_days=look_ahead_days,
        )
        return {
            "sessions": [_session_to_dict(s) for s in updated],
            "changes": log,
        }


def _session_to_dict(session: HabitSession) -> dict:
    return {
        "id": session.id,
        "habit_id": session.habit_id,
        "habit_title": session.habit_title,
        "start_time": session.start.isoformat(),
        "end_time": session.end.isoformat(),
        "explanation": session.explanation,
        "score": session.score,
        "is_habit": True,
        "is_ai_generated": False,
    }
