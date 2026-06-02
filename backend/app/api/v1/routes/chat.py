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


@router.post("/message")
async def post_message(body: ChatMessageIn) -> dict:
    service = ChatService()
    events = list(body.calendar_events)
    tasks = list(body.tasks)
    reply = await service.process_message(
        body.message,
        body.user_id,
        calendar_events=events,
        tasks=tasks,
        client_today=body.client_today.strip() or None,
        timezone_offset_minutes=body.timezone_offset_minutes,
        timezone_name=body.timezone_name.strip() or None,
    )
    return {"reply": reply}
