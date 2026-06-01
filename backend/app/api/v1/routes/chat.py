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


class TaskIn(BaseModel):
    id: str = ""
    title: str = ""
    due_date: str
    estimated_minutes: int = Field(default=180, ge=1)
    course_name: str = ""
    source: str = ""
    is_completed: bool = False


class ChatMessageIn(BaseModel):
    message: str
    user_id: str = Field(default="anon", description="Client user id for future session state.")
    calendar_events: list[CalendarEventIn] = Field(
        default_factory=list,
        description="Calendar events from iCal/course/manual/Canvas (same as Calendar tab).",
    )
    tasks: list[TaskIn] = Field(
        default_factory=list,
        description="Tasks from the Tasks tab (manual + cached Canvas).",
    )


@router.post("/message")
async def post_message(body: ChatMessageIn) -> dict:
    service = ChatService()
    events = [e.model_dump() for e in body.calendar_events]
    tasks = [t.model_dump() for t in body.tasks]
    reply = await service.process_message(
        body.message,
        body.user_id,
        calendar_events=events,
        tasks=tasks,
    )
    return {"reply": reply}
