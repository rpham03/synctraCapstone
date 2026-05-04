# API routes for retrieving and regenerating AI-suggested schedule blocks.
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field

from app.services.scheduler_service import FixedEvent, SchedulerService, Task

router = APIRouter()


class FixedEventIn(BaseModel):
    start: datetime
    end: datetime


class TaskIn(BaseModel):
    id: str
    title: str
    due_date: datetime
    estimated_minutes: int = Field(ge=1)


class SuggestScheduleIn(BaseModel):
    tasks: list[TaskIn]
    fixed_events: list[FixedEventIn] = Field(default_factory=list)
    look_ahead_days: int = Field(default=7, ge=1, le=366)


@router.post("/suggest")
async def suggest_schedule(body: SuggestScheduleIn) -> dict:
    service = SchedulerService()
    tasks = [
        Task(
            id=t.id,
            title=t.title,
            due_date=t.due_date,
            estimated_minutes=t.estimated_minutes,
        )
        for t in body.tasks
    ]
    fixed = [FixedEvent(start=f.start, end=f.end) for f in body.fixed_events]
    blocks = service.suggest_blocks(tasks, fixed, body.look_ahead_days)
    return {
        "blocks": [
            {
                "id": b.id,
                "task_id": b.task_id,
                "task_title": b.task_title,
                "start_time": b.start.isoformat(),
                "end_time": b.end.isoformat(),
                "is_ai_generated": True,
            }
            for b in blocks
        ]
    }
