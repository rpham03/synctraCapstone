# API routes for fetching and managing fixed calendar events (classes, meetings, exams).
from datetime import date, datetime, timezone, timedelta
import uuid as _uuid

import httpx
import recurring_ical_events
from fastapi import APIRouter, HTTPException
from icalendar import Calendar
from pydantic import BaseModel

router = APIRouter()


class IcalFeedIn(BaseModel):
    url: str
    name: str = ""


@router.post("/ical-feeds/preview")
async def preview_ical_feed(body: IcalFeedIn) -> dict:
    """Fetch an iCal URL and return its events as JSON.

    Recurring events (RRULE) are fully expanded — e.g. a Canvas lecture
    that repeats every Monday/Wednesday for 16 weeks becomes 32 individual
    events. Covers a window of 90 days in the past to 365 days in the future.
    """
    url = body.url
    if url.startswith("webcal://"):
        url = url.replace("webcal://", "https://", 1)

    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            resp = await client.get(url)
            resp.raise_for_status()
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=400, detail=f"Could not fetch iCal URL: {exc}")

    try:
        cal = Calendar.from_ical(resp.content)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Invalid iCal data: {exc}")

    # Extract calendar display name
    feed_name = body.name
    if not feed_name:
        for comp in cal.walk():
            if comp.name == "VCALENDAR":
                feed_name = str(comp.get("X-WR-CALNAME", "")) or "iCal Feed"
                break

    # Expand recurrences over a ~15-month window (past semester + next year)
    now = datetime.now(tz=timezone.utc)
    start_dt = now - timedelta(days=90)
    end_dt   = now + timedelta(days=365)

    try:
        expanded = recurring_ical_events.of(cal).between(start_dt, end_dt)
    except Exception:
        # Fallback: walk components without expansion if library fails
        expanded = [c for c in cal.walk() if c.name == "VEVENT"]

    events: list[dict] = []
    for component in expanded:
        dtstart = component.get("DTSTART")
        if dtstart is None:
            continue

        dtend = component.get("DTEND")
        start = dtstart.dt
        end   = dtend.dt if dtend else start

        # Normalise all-day date → midnight datetime
        if isinstance(start, date) and not isinstance(start, datetime):
            start = datetime(start.year, start.month, start.day, 0, 0, 0)
        if isinstance(end, date) and not isinstance(end, datetime):
            end = datetime(end.year, end.month, end.day, 23, 59, 59)

        # Strip tz info for uniform ISO strings
        if getattr(start, "tzinfo", None):
            start = start.replace(tzinfo=None)
        if getattr(end, "tzinfo", None):
            end = end.replace(tzinfo=None)

        uid = str(component.get("UID", _uuid.uuid4()))
        # Append start time to UID so each recurrence gets a unique ID
        unique_id = f"{uid}_{start.isoformat()}"

        events.append({
            "id":         unique_id,
            "title":      str(component.get("SUMMARY", "Untitled")),
            "start_time": start.isoformat(),
            "end_time":   end.isoformat(),
            "source":     "ical",
            "is_fixed":   True,
        })

    return {
        "feed_name":   feed_name or "iCal Feed",
        "event_count": len(events),
        "events":      events,
    }
