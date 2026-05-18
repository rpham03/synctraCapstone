# API routes for receiving chat messages and returning AI-driven schedule actions.
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.chat_service import ChatService

router = APIRouter()


class CalendarEventIn(BaseModel):
    start_time: str
    end_time: str
    title: str = ""
    source: str = ""


class ChatMessageIn(BaseModel):
    message: str
    user_id: str = Field(default="anon", description="Client user id for future session state.")
    calendar_events: list[CalendarEventIn] = Field(
        default_factory=list,
        description="Busy blocks from iCal/course calendar (same as Calendar tab).",
    )


@router.post("/message")
async def post_message(body: ChatMessageIn) -> dict:
    service = ChatService()
    events = [e.model_dump() for e in body.calendar_events]
    reply = await service.process_message(
        body.message,
        body.user_id,
        calendar_events=events,
    )
    return {"reply": reply}
