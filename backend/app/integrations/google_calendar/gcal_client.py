# Google Calendar API client — reads and writes events on a user's Google Calendar.
"""Google Calendar API client — fetches and creates calendar events."""
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build


class GoogleCalendarClient:
    SCOPES = ["https://www.googleapis.com/auth/calendar"]

    def __init__(self, credentials: Credentials):
        self.service = build("calendar", "v3", credentials=credentials)

    def get_events(self, calendar_id: str = "primary", max_results: int = 100) -> list[dict]:
        result = (
            self.service.events()
            .list(calendarId=calendar_id, maxResults=max_results, singleEvents=True, orderBy="startTime")
            .execute()
        )
        return result.get("items", [])

    def create_event(self, calendar_id: str, event_body: dict) -> dict:
        return self.service.events().insert(calendarId=calendar_id, body=event_body).execute()
