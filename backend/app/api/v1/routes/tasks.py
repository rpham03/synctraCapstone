# API routes for fetching and managing flexible tasks (homework, study, project work).
from fastapi import APIRouter

router = APIRouter()


@router.get("/")
async def list_tasks() -> dict:
    """Return tasks for the signed-in user (stub until Canvas/DB sync is connected)."""
    return {"tasks": []}
