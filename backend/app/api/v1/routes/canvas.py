# Canvas LMS — fetch assignments for the configured student token (UW instance by default).
import httpx
from fastapi import APIRouter, HTTPException

from app.core.config.settings import settings
from app.integrations.canvas.canvas_client import CanvasClient

router = APIRouter()


@router.get("/assignments")
async def list_canvas_assignments() -> dict:
    """Return assignments from Canvas as Synctra task-shaped JSON.

    Requires ``CANVAS_API_TOKEN`` in the backend environment. Never log the token.
    """
    token = (settings.canvas_api_token or "").strip()
    if not token:
        raise HTTPException(
            status_code=503,
            detail="Configure CANVAS_API_TOKEN (and CANVAS_API_BASE_URL if not UW) in .env.",
        )
    client = CanvasClient(token)
    try:
        tasks = await client.list_tasks_normalized()
    except httpx.HTTPStatusError as e:
        detail = e.response.text[:500] if e.response is not None else str(e)
        raise HTTPException(
            status_code=502,
            detail=f"Canvas API returned {e.response.status_code if e.response else '?'}: {detail}",
        ) from e
    except httpx.RequestError as e:
        raise HTTPException(status_code=502, detail=f"Canvas request failed: {e}") from e
    return {"tasks": tasks}
