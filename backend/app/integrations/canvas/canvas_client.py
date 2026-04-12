# Canvas LMS API client — fetches courses, assignments, and due dates for a student.
"""Canvas LMS API client — fetches assignments, courses, and due dates."""
import httpx
from app.core.config.settings import settings


class CanvasClient:
    BASE_URL = "https://canvas.instructure.com/api/v1"

    def __init__(self, api_token: str):
        self.headers = {"Authorization": f"Bearer {api_token}"}

    async def get_courses(self) -> list[dict]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(f"{self.BASE_URL}/courses", headers=self.headers)
            resp.raise_for_status()
            return resp.json()

    async def get_assignments(self, course_id: str) -> list[dict]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.BASE_URL}/courses/{course_id}/assignments",
                headers=self.headers,
            )
            resp.raise_for_status()
            return resp.json()
