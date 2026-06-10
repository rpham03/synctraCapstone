# Canvas LMS — fetch assignments for the student's personal access token.
import httpx
from fastapi import APIRouter, Header, HTTPException

from app.core.config.settings import settings
from app.integrations.canvas.canvas_client import CanvasClient

router = APIRouter()


@router.get("/assignments")
async def list_canvas_assignments(
    x_canvas_token: str | None = Header(default=None),
    x_canvas_base_url: str | None = Header(default=None),
) -> dict:
    """Return the student's assignments from Canvas as Synctra task-shaped JSON.

    The student's personal access token is sent per-request from the app
    (``X-Canvas-Token``); it falls back to ``CANVAS_API_TOKEN`` in the backend
    environment. Never log the token.
    """
    token = (x_canvas_token or settings.canvas_api_token or "").strip()
    if not token:
        raise HTTPException(
            status_code=503,
            detail="No Canvas token. Add your Canvas access token in Settings → Integrations.",
        )
    base_url = (x_canvas_base_url or "").strip() or None
    client = CanvasClient(token, base_url=base_url)
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
