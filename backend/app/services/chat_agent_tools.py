# Tool implementations invoked by the OpenAI schedule agent.
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx
from dateutil import parser as date_parser

from app.core.config.settings import settings
from app.integrations.canvas.canvas_client import CanvasClient
from app.services.chat_calendar_context import get_calendar_events
from app.services.scheduler_service import SchedulerService, Task

# Default “calendar day” window when no iCal events are supplied yet.
_WORKDAY_START_HOUR = 8
_WORKDAY_END_HOUR = 22
_MIN_SLOT_MINUTES = 60


def today_local() -> date:
    return datetime.now().date()


def week_range_mon_fri(anchor: date | None = None) -> tuple[str, str]:
    """ISO dates (YYYY-MM-DD) for Monday–Friday of the week containing anchor."""
    d = anchor or today_local()
    monday = d - timedelta(days=d.weekday())
    friday = monday + timedelta(days=4)
    return monday.isoformat(), friday.isoformat()


def sanitize_free_slot_range(start_date: str, end_date: str) -> tuple[str, str, bool]:
    """If the model passed stale dates (e.g. March when today is May), use this week."""
    today = today_local()
    try:
        start_d = _parse_date_bound(start_date, end_of_day=False).date()
        end_d = _parse_date_bound(end_date, end_of_day=True).date()
    except (ValueError, TypeError):
        mon, fri = week_range_mon_fri(today)
        return mon, fri, True

    if end_d < today:
        mon, fri = week_range_mon_fri(today)
        return mon, fri, True

    return start_d.isoformat(), end_d.isoformat(), False


def _as_str(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        return str(value)
    return str(value)


def _parse_iso_datetime(value: object) -> datetime:
    text = _as_str(value).strip()
    if not text:
        raise ValueError("missing date")
    dt = date_parser.parse(text)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def _parse_date_bound(value: object, *, end_of_day: bool) -> datetime:
    text = _as_str(value).strip()
    dt = _parse_iso_datetime(text)
    if len(text) <= 10:
        if end_of_day:
            return dt.replace(hour=23, minute=59, second=59, microsecond=0)
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    return dt


async def get_assignments_from_canvas() -> dict:
    """Canvas assignments in Synctra task shape (last 7 days + upcoming)."""
    token = (settings.canvas_api_token or "").strip()
    if not token:
        return {
            "assignments": [],
            "error": "CANVAS_API_TOKEN is not configured on the server.",
        }
    client = CanvasClient(token)
    try:
        tasks = await client.list_tasks_normalized()
    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response is not None else "?"
        detail = (e.response.text or str(e))[:300] if e.response is not None else str(e)
        return {"assignments": [], "error": f"Canvas API {status}: {detail}"}
    except httpx.RequestError as e:
        return {"assignments": [], "error": f"Canvas request failed: {e}"}
    return {"assignments": tasks, "count": len(tasks)}


def _parse_busy_event(raw: dict) -> tuple[datetime, datetime, str] | None:
    try:
        start = _parse_iso_datetime(raw.get("start_time"))
        end = _parse_iso_datetime(raw.get("end_time"))
    except (ValueError, TypeError):
        return None
    if end <= start:
        return None
    title = _as_str(raw.get("title")).strip() or "Busy"
    return start, end, title


def _merge_busy(
    intervals: list[tuple[datetime, datetime]],
) -> list[tuple[datetime, datetime]]:
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda x: x[0])
    merged: list[tuple[datetime, datetime]] = [ordered[0]]
    for start, end in ordered[1:]:
        ps, pe = merged[-1]
        if start <= pe:
            merged[-1] = (ps, max(pe, end))
        else:
            merged.append((start, end))
    return merged


def _gaps_between_busy(
    work_start: datetime,
    work_end: datetime,
    busy: list[tuple[datetime, datetime]],
    *,
    min_duration: timedelta,
) -> list[tuple[datetime, datetime]]:
    clipped: list[tuple[datetime, datetime]] = []
    for bs, be in busy:
        s = max(bs, work_start)
        e = min(be, work_end)
        if s < e:
            clipped.append((s, e))
    merged = _merge_busy(clipped)
    gaps: list[tuple[datetime, datetime]] = []
    cursor = work_start
    for bs, be in merged:
        if cursor + min_duration <= bs:
            gaps.append((cursor, bs))
        cursor = max(cursor, be)
    if cursor + min_duration <= work_end:
        gaps.append((cursor, work_end))
    return gaps


def find_free_slots_in_calendar(start_date: str, end_date: str) -> dict:
    """Open blocks between calendar/iCal busy times within daily work hours."""
    start_iso, end_iso, corrected = sanitize_free_slot_range(start_date, end_date)
    start = _parse_date_bound(start_iso, end_of_day=False)
    end = _parse_date_bound(end_iso, end_of_day=True)
    if end < start:
        return {"slots": [], "error": "end_date must be on or after start_date"}

    calendar_events = get_calendar_events()
    parsed_busy: list[tuple[datetime, datetime, str]] = []
    for raw in calendar_events:
        if not isinstance(raw, dict):
            continue
        row = _parse_busy_event(raw)
        if row:
            parsed_busy.append(row)

    min_duration = timedelta(minutes=_MIN_SLOT_MINUTES)
    slots: list[dict] = []
    day_cursor = start.date()
    last_day = end.date()

    while day_cursor <= last_day:
        day_start = datetime(
            day_cursor.year,
            day_cursor.month,
            day_cursor.day,
            _WORKDAY_START_HOUR,
            0,
            0,
        )
        day_end = datetime(
            day_cursor.year,
            day_cursor.month,
            day_cursor.day,
            _WORKDAY_END_HOUR,
            0,
            0,
        )
        work_start = max(day_start, start)
        work_end = min(day_end, end)
        if work_start >= work_end:
            day_cursor = day_cursor + timedelta(days=1)
            continue

        day_busy = [
            (bs, be) for bs, be, _ in parsed_busy if bs < work_end and be > work_start
        ]
        for gap_start, gap_end in _gaps_between_busy(
            work_start, work_end, day_busy, min_duration=min_duration
        ):
            slots.append(
                {
                    "start": gap_start.isoformat(),
                    "end": gap_end.isoformat(),
                    "minutes_available": int(
                        (gap_end - gap_start).total_seconds() // 60
                    ),
                }
            )
        day_cursor = day_cursor + timedelta(days=1)

    today = today_local()
    mon, fri = week_range_mon_fri(today)
    if parsed_busy:
        note = (
            f"Free time between your calendar events ({len(parsed_busy)} busy blocks "
            "from the app) within 8am–10pm work hours."
        )
    else:
        note = (
            "No calendar events were sent from the app; showing full work-day "
            "windows (8am–10pm). "
            "Open Calendar to sync iCal feeds, then ask again in Chat."
        )
    if corrected:
        note += (
            f" Stale dates corrected to this week ({mon}–{fri}); "
            f"today is {today.isoformat()}."
        )
    return {
        "slots": slots,
        "start_date": start_iso,
        "end_date": end_iso,
        "today": today.isoformat(),
        "this_week_mon_fri": {"monday": mon, "friday": fri},
        "dates_corrected": corrected,
        "calendar_events_used": len(parsed_busy),
        "note": note,
    }


def propose_schedule_change(task_name: object, hours: object, deadline: object) -> dict:
    """Propose study blocks without writing to the calendar."""
    deadline_str = _as_str(deadline).strip()
    if not deadline_str:
        return {"proposal": [], "message": "A deadline date is required."}
    try:
        due = _parse_iso_datetime(deadline_str)
    except (ValueError, TypeError) as e:
        return {"proposal": [], "message": f"Could not parse deadline: {e}"}
    try:
        hours_f = float(hours) if not isinstance(hours, str) else float(hours.strip())
    except (TypeError, ValueError):
        hours_f = 1.0
    minutes = max(15, int(round(hours_f * 60)))
    task = Task(
        id="chat-proposal",
        title=_as_str(task_name).strip() or "Study block",
        due_date=due,
        estimated_minutes=minutes,
    )
    service = SchedulerService()
    look_ahead = max(1, min(60, (due.date() - date.today()).days + 1))
    blocks = service.suggest_blocks(
        [task],
        fixed_events=[],
        look_ahead_days=look_ahead,
    )
    if not blocks:
        return {
            "proposal": [],
            "message": (
                f"Could not place {hours}h for “{task_name}” before {deadline}. "
                "Try a later deadline or shorter duration."
            ),
        }
    proposal = [
        {
            "task_title": b.task_title,
            "start_time": b.start.isoformat(),
            "end_time": b.end.isoformat(),
            "is_ai_generated": True,
            "written_to_calendar": False,
        }
        for b in blocks
    ]
    return {
        "proposal": proposal,
        "message": "Proposal only — not saved to your calendar yet.",
    }
