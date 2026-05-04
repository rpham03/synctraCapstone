# API routes for receiving chat messages and returning AI-driven schedule actions.
from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.chat_service import ChatService

router = APIRouter()


class ChatMessageIn(BaseModel):
    message: str
    user_id: str = Field(default="anon", description="Client user id for future session state.")


@router.post("/message")
async def post_message(body: ChatMessageIn) -> dict:
    service = ChatService()
    reply = await service.process_message(body.message, body.user_id)
    return {"reply": reply}
