# API routes for receiving chat messages and returning AI-driven schedule actions.
from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.chat_service import ChatService

router = APIRouter()


class ChatMessageIn(BaseModel):
    message: str
    user_id: str = Field(default="anon", description="Client user id for future session state.")
    client_today: str = Field(
        default="",
        description="Device-local today as YYYY-MM-DD (must match Calendar/Tasks tabs).",
    )
    timezone_offset_minutes: int = Field(
        default=0,
        description="Client timezone offset from UTC in minutes (e.g. -420 for PDT).",
    )
    timezone_name: str = Field(
        default="",
        description="Device timezone abbreviation (e.g. PDT, PST, EST).",
    )
    calendar_events: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Calendar events from iCal/course/manual/Canvas (same as Calendar tab).",
    )
    tasks: list[dict[str, Any]] = Field(
        default_factory=list,
        description="Tasks from the Tasks tab (manual + cached Canvas + course).",
    )
    study_start_time: str = Field(
        default="",
        description="Settings study-window start as HH:MM (latest user_settings).",
    )
    study_end_time: str = Field(
        default="",
        description="Settings study-window end as HH:MM (latest user_settings).",
    )
    session_length_minutes: int = Field(
        default=0,
        description="Preferred study-session length in minutes (0 = use default).",
    )
    break_minutes: int = Field(
        default=0,
        description="Break to leave between scheduled blocks in minutes (0 = default).",
    )


@router.post("/message")
async def post_message(body: ChatMessageIn) -> dict:
    service = ChatService()
    events = list(body.calendar_events)
    tasks = list(body.tasks)
    study_preferences = {
        "start": body.study_start_time.strip(),
        "end": body.study_end_time.strip(),
        "session_minutes": body.session_length_minutes,
        "break_minutes": body.break_minutes,
    }
    print(
        f"[chat] msg={body.message!r} tasks_in={len(tasks)} "
        f"events_in={len(events)} client_today={body.client_today!r} "
        f"study_window={body.study_start_time!r}-{body.study_end_time!r} "
        f"session={body.session_length_minutes} break={body.break_minutes}",
        flush=True,
    )
    reply, proposals = await service.process_message(
        body.message,
        body.user_id,
        calendar_events=events,
        tasks=tasks,
        client_today=body.client_today.strip() or None,
        timezone_offset_minutes=body.timezone_offset_minutes,
        timezone_name=body.timezone_name.strip() or None,
        study_preferences=study_preferences,
    )
    return {"reply": reply, "schedule_proposals": proposals}
