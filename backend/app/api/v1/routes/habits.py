"""Habit CRUD and scheduling API — Reclaim-style flexible habit placement."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.models.habit_models import CalendarEvent, HabitSession
from app.services.habit_repository import HabitRepository
from app.services.habit_service import HabitService

router = APIRouter()
_service = HabitService()


def _user_id(x_user_id: Optional[str]) -> str:
    return (x_user_id or "default").strip() or "default"


class TimeRangeIn(BaseModel):
    start: str = Field(description="Clock time e.g. 11:30am or 14:00")
    end: str


class HabitCreateIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    duration_minutes: int = Field(ge=5, le=480)
    duration_max_minutes: Optional[int] = Field(default=None, ge=5, le=480)
    frequency_per_week: int = Field(ge=1, le=14)
    preferred_days: List[int] = Field(
        default_factory=list,
        description="0=Monday … 6=Sunday",
    )
    preferred_time_ranges: Dict[str, List[TimeRangeIn]] = Field(
        default_factory=dict,
        description="Day key -> list of ranges, e.g. {'0': [{'start':'11:30am','end':'2:00pm'}]}",
    )
    priority: int = Field(ge=1, le=10, default=5)
    is_active: bool = True


class HabitUpdateIn(BaseModel):
    title: Optional[str] = Field(default=None, min_length=1, max_length=200)
    duration_minutes: Optional[int] = Field(default=None, ge=5, le=480)
    duration_max_minutes: Optional[int] = Field(default=None, ge=5, le=480)
    frequency_per_week: Optional[int] = Field(default=None, ge=1, le=14)
    preferred_days: Optional[List[int]] = None
    preferred_time_ranges: Optional[Dict[str, List[TimeRangeIn]]] = None
    priority: Optional[int] = Field(default=None, ge=1, le=10)
    is_active: Optional[bool] = None


class CalendarEventIn(BaseModel):
    id: str = "event"
    title: str = "Busy"
    start: datetime
    end: datetime
    source: str = "calendar"


class HabitSessionIn(BaseModel):
    id: str
    habit_id: str
    habit_title: str
    start_time: datetime
    end_time: datetime
    explanation: str = ""


class ScheduleWeekIn(BaseModel):
    calendar_events: List[CalendarEventIn] = Field(default_factory=list)
    week_start: Optional[datetime] = None
    look_ahead_days: int = Field(default=7, ge=1, le=28)


class RescheduleIn(BaseModel):
    calendar_events: List[CalendarEventIn] = Field(default_factory=list)
    current_sessions: List[HabitSessionIn] = Field(default_factory=list)
    new_event: CalendarEventIn
    week_start: Optional[datetime] = None
    look_ahead_days: int = Field(default=7, ge=1, le=28)


def _habit_to_dict(habit) -> dict:
    return {
        "id": habit.id,
        "user_id": habit.user_id,
        "title": habit.title,
        "duration_minutes": habit.duration_minutes,
        "duration_max_minutes": max(habit.duration_max_minutes, habit.duration_minutes),
        "frequency_per_week": habit.frequency_per_week,
        "preferred_days": habit.preferred_days,
        "preferred_time_ranges": {
            str(day): [
                {
                    "start": _minutes_to_display(tr.start_minutes),
                    "end": _minutes_to_display(tr.end_minutes),
                }
                for tr in ranges
            ]
            for day, ranges in habit.preferred_time_ranges.items()
        },
        "priority": habit.priority,
        "is_active": habit.is_active,
        "created_at": habit.created_at.isoformat(),
        "updated_at": habit.updated_at.isoformat(),
    }


def _minutes_to_display(minutes: int) -> str:
    hour = minutes // 60
    minute = minutes % 60
    meridiem = "am" if hour < 12 else "pm"
    display = hour % 12 or 12
    if minute:
        return f"{display}:{minute:02d}{meridiem}"
    return f"{display}{meridiem}"


def _to_calendar_events(items: List[CalendarEventIn]) -> List[CalendarEvent]:
    return [
        CalendarEvent(
            id=e.id,
            title=e.title,
            start=e.start,
            end=e.end,
            source=e.source,
        )
        for e in items
    ]


def _to_sessions(items: List[HabitSessionIn]) -> List[HabitSession]:
    return [
        HabitSession(
            id=s.id,
            habit_id=s.habit_id,
            habit_title=s.habit_title,
            start=s.start_time,
            end=s.end_time,
            explanation=s.explanation,
        )
        for s in items
    ]


@router.get("")
async def list_habits(
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
) -> dict:
    user = _user_id(x_user_id)
    habits = _service.list_habits(user)
    return {"habits": [_habit_to_dict(h) for h in habits]}


@router.post("")
async def create_habit(
    body: HabitCreateIn,
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
) -> dict:
    user = _user_id(x_user_id)
    payload = body.model_dump()
    payload["preferred_time_ranges"] = {
        day: [r.model_dump() for r in ranges]
        for day, ranges in body.preferred_time_ranges.items()
    }
    habit = _service.create_habit(user, payload)
    return {"habit": _habit_to_dict(habit)}


@router.put("/{habit_id}")
async def update_habit(
    habit_id: str,
    body: HabitUpdateIn,
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
) -> dict:
    user = _user_id(x_user_id)
    payload: Dict[str, Any] = body.model_dump(exclude_unset=True)
    if body.preferred_time_ranges is not None:
        payload["preferred_time_ranges"] = {
            day: [r.model_dump() for r in ranges]
            for day, ranges in body.preferred_time_ranges.items()
        }
    habit = _service.update_habit(user, habit_id, payload)
    if habit is None:
        raise HTTPException(status_code=404, detail="Habit not found")
    return {"habit": _habit_to_dict(habit)}


@router.delete("/{habit_id}")
async def delete_habit(
    habit_id: str,
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
) -> dict:
    user = _user_id(x_user_id)
    if not _service.delete_habit(user, habit_id):
        raise HTTPException(status_code=404, detail="Habit not found")
    return {"deleted": True, "id": habit_id}


@router.post("/schedule")
async def schedule_habits(
    body: ScheduleWeekIn,
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
) -> dict:
    """Place all active habits into free slots for the week."""
    user = _user_id(x_user_id)
    result = _service.schedule_week(
        user,
        _to_calendar_events(body.calendar_events),
        week_start=body.week_start,
        look_ahead_days=body.look_ahead_days,
    )
    return result


@router.post("/reschedule")
async def reschedule_habits(
    body: RescheduleIn,
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
) -> dict:
    """After a new fixed event is added, move conflicting habit sessions."""
    user = _user_id(x_user_id)
    return _service.reschedule_for_new_event(
        user,
        _to_calendar_events(body.calendar_events),
        _to_sessions(body.current_sessions),
        CalendarEvent(
            id=body.new_event.id,
            title=body.new_event.title,
            start=body.new_event.start,
            end=body.new_event.end,
            source=body.new_event.source,
        ),
        week_start=body.week_start,
        look_ahead_days=body.look_ahead_days,
    )
