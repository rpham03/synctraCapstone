# Canvas LMS API client — fetches courses, assignments, and due dates for a student.
"""Canvas LMS API client — fetches assignments, courses, and due dates."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import httpx
from app.core.config.settings import settings


def _estimate_minutes(assignment: dict) -> int:
    pts = assignment.get("points_possible")
    if isinstance(pts, (int, float)) and pts and pts > 0:
        return min(int(pts * 3), 240)
    return 60


def _submission_done(submission: dict | None) -> bool:
    if not submission:
        return False
    wf = submission.get("workflow_state") or ""
    return wf in ("submitted", "graded", "pending_review", "complete")


def _due_at_in_view_window(due_at_iso: object, *, days_past: int = 7) -> bool:
    """True if due is in [now - days_past, +infinity) — last week of history + all upcoming."""
    if not isinstance(due_at_iso, str):
        return False
    s = due_at_iso.strip()
    if not s:
        return False
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    due = datetime.fromisoformat(s)
    if due.tzinfo is None:
        due = due.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days_past)
    return due >= cutoff


class CanvasClient:
    def __init__(self, api_token: str, base_url: str | None = None):
        self.base_url = (base_url or settings.canvas_api_base_url).rstrip("/")
        self.headers = {"Authorization": f"Bearer {api_token}"}

    async def list_active_courses(self) -> list[dict]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(
                f"{self.base_url}/courses",
                headers=self.headers,
                params={"enrollment_state": "active", "per_page": 100},
            )
            resp.raise_for_status()
            rows = resp.json()
            if not isinstance(rows, list):
                return []
            return [c for c in rows if isinstance(c, dict) and c.get("id") is not None]

    async def get_assignments(
        self, course_id: str, *, include_submission: bool = False
    ) -> list[dict]:
        params: dict[str, str | int] = {"per_page": 100}
        if include_submission:
            params["include[]"] = "submission"
        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.get(
                f"{self.base_url}/courses/{course_id}/assignments",
                headers=self.headers,
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []

    async def list_tasks_normalized(self) -> list[dict]:
        """Synctra task JSON for assignments due in the last 7 days or anytime in the future.

        Older due dates (e.g. last term) are omitted so the list stays focused on
        the past week + upcoming work.
        """
        courses = await self.list_active_courses()
        out: list[dict] = []
        for c in courses:
            cid = c.get("id")
            if cid is None:
                continue
            course_id_str = str(int(cid)) if isinstance(cid, (int, float)) else str(cid)
            try:
                assigns = await self.get_assignments(
                    course_id_str, include_submission=True
                )
            except httpx.HTTPStatusError:
                continue
            for a in assigns:
                if not isinstance(a, dict):
                    continue
                if not a.get("published", True):
                    continue
                due = a.get("due_at")
                if not due or not isinstance(due, str):
                    continue
                if not _due_at_in_view_window(due, days_past=7):
                    continue
                aid = a.get("id")
                if aid is None:
                    continue
                raw_name = a.get("name") or "Assignment"
                title = raw_name.strip() if isinstance(raw_name, str) else "Assignment"
                sub = a.get("submission")
                if isinstance(sub, list):
                    sub = sub[0] if sub else None
                if sub is not None and not isinstance(sub, dict):
                    sub = None
                out.append(
                    {
                        "id": f"{course_id_str}_{aid}",
                        "title": title,
                        "due_date": due,
                        "estimated_minutes": _estimate_minutes(a),
                        "course_id": course_id_str,
                        "source": "canvas",
                        "is_completed": _submission_done(sub),
                    }
                )
        out.sort(key=lambda t: t["due_date"])
        return out

    async def get_courses(self) -> list[dict]:
        return await self.list_active_courses()
