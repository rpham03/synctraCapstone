# Tool implementations invoked by the OpenAI schedule agent.
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import httpx
from dateutil import parser as date_parser

from app.core.config.settings import settings
from app.integrations.canvas.canvas_client import CanvasClient
from app.services.chat_client_context import (
    effective_now,
    effective_today,
    get_calendar_events,
    get_tasks,
)
from app.services.scheduler_service import SchedulerService, Task

# Default “calendar day” window when no iCal events are supplied yet.
_WORKDAY_START_HOUR = 8
_WORKDAY_END_HOUR = 22
_MIN_SLOT_MINUTES = 60


def today_local() -> date:
    """Server date — prefer [effective_today] when handling chat requests."""
    return datetime.now().date()


def _event_local_date(raw: dict) -> date | None:
    ld = _as_str(raw.get("local_date")).strip()
    if ld:
        try:
            return date.fromisoformat(ld[:10])
        except ValueError:
            pass
    row = _parse_busy_event(raw)
    if row:
        return row[0].date()
    return None


def _task_local_due_date(raw: dict) -> date | None:
    ld = _as_str(raw.get("local_due_date")).strip()
    if ld:
        try:
            return date.fromisoformat(ld[:10])
        except ValueError:
            pass
    try:
        return _parse_iso_datetime(raw.get("due_date")).date()
    except (ValueError, TypeError):
        return None


def _event_in_date_range(raw: dict, start_d: date, end_d: date) -> bool:
    local = _event_local_date(raw)
    if local is not None:
        return start_d <= local <= end_d
    row = _parse_busy_event(raw)
    if not row:
        return False
    bs, be, _ = row
    return bs.date() <= end_d and be.date() >= start_d


def week_range_mon_fri(anchor: date | None = None) -> tuple[str, str]:
    """ISO dates (YYYY-MM-DD) for Monday–Friday of the week containing anchor."""
    d = anchor or today_local()
    monday = d - timedelta(days=d.weekday())
    friday = monday + timedelta(days=4)
    return monday.isoformat(), friday.isoformat()


def sanitize_free_slot_range(start_date: str, end_date: str) -> tuple[str, str, bool]:
    """If the model passed stale dates (e.g. March when today is May), use this week."""
    today = effective_today()
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


def format_local_time(dt: datetime) -> str:
    """12-hour clock for wall-clock times from the user's device."""
    hour = dt.hour
    minute = dt.minute
    h12 = hour % 12 or 12
    suffix = "AM" if hour < 12 else "PM"
    return f"{h12}:{minute:02d} {suffix}"


def format_local_time_range(start: datetime, end: datetime) -> str:
    return f"{format_local_time(start)} – {format_local_time(end)}"


def _event_time_label(raw: dict, start: datetime, end: datetime) -> str | None:
    if raw.get("is_all_day"):
        when = _as_str(raw.get("when_label")).strip()
        return when or None
    label = _as_str(raw.get("time_label")).strip()
    if label:
        return label
    return format_local_time_range(start, end)


def _format_date_short(dt: datetime) -> str:
    return dt.strftime("%a, %b %d").replace(" 0", " ")


def _event_when_label(raw: dict, start: datetime, end: datetime) -> str:
    when = _as_str(raw.get("when_label")).strip()
    if when:
        return when
    if raw.get("is_all_day"):
        return _format_date_short(start)
    return f"{_format_date_short(start)} · {format_local_time_range(start, end)}"


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
    """Canvas assignments due today or later (local calendar day)."""
    token = (settings.canvas_api_token or "").strip()
    if not token:
        return {
            "assignments": [],
            "error": "CANVAS_API_TOKEN is not configured on the server.",
        }
    client = CanvasClient(token)
    try:
        tasks = await client.list_tasks_normalized(omit_completed=True)
    except httpx.HTTPStatusError as e:
        status = e.response.status_code if e.response is not None else "?"
        detail = (e.response.text or str(e))[:300] if e.response is not None else str(e)
        return {"assignments": [], "error": f"Canvas API {status}: {detail}"}
    except httpx.RequestError as e:
        return {"assignments": [], "error": f"Canvas request failed: {e}"}
    enriched = [_assignment_with_display_label(t) for t in tasks]
    return {"assignments": enriched, "count": len(enriched)}


def _assignment_with_display_label(task: dict) -> dict:
    """Add a human-readable label: course + assignment title."""
    title = (task.get("title") or "Assignment").strip()
    course = (task.get("course_name") or "").strip()
    out = dict(task)
    out["display_label"] = f"{course} — {title}" if course else title
    return out


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
                    "time_label": format_local_time_range(gap_start, gap_end),
                    "minutes_available": int(
                        (gap_end - gap_start).total_seconds() // 60
                    ),
                }
            )
        day_cursor = day_cursor + timedelta(days=1)

    today = effective_today()
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


def _task_with_display_label(task: dict) -> dict:
    """Add display_label for manual/Canvas tasks from the app."""
    title = (task.get("title") or "Task").strip()
    course = (task.get("course_name") or "").strip()
    out = dict(task)
    out["display_label"] = f"{course} — {title}" if course else title
    return out


def list_calendar_events_for_range(start_date: str, end_date: str) -> dict:
    """List timed calendar events (iCal, course, manual) sent from the app."""
    start_iso, end_iso, corrected = sanitize_free_slot_range(start_date, end_date)
    start = _parse_date_bound(start_iso, end_of_day=False)
    end = _parse_date_bound(end_iso, end_of_day=True)
    if end < start:
        return {"events": [], "error": "end_date must be on or after start_date"}

    start_d = start.date()
    end_d = end.date()
    events_out: list[dict] = []
    for raw in get_calendar_events():
        if not isinstance(raw, dict):
            continue
        if not _event_in_date_range(raw, start_d, end_d):
            continue
        row = _parse_busy_event(raw)
        if not row:
            continue
        bs, be, title = row
        source = _as_str(raw.get("source")).strip() or "calendar"
        local = _event_local_date(raw)
        events_out.append(
            {
                "title": title,
                "start_time": bs.isoformat(),
                "end_time": be.isoformat(),
                "local_date": local.isoformat() if local else None,
                "time_label": _event_time_label(raw, bs, be),
                "when_label": _event_when_label(raw, bs, be),
                "source": source,
                "is_all_day": bool(raw.get("is_all_day")),
            }
        )
    events_out.sort(key=lambda e: e["start_time"])

    today = effective_today()
    mon, fri = week_range_mon_fri(today)
    if events_out:
        note = (
            f"{len(events_out)} calendar event(s) from the app "
            "(iCal feeds, course imports, manual events, Canvas due chips)."
        )
    else:
        note = (
            "No calendar events in this range were sent from the app. "
            "Open the Calendar tab to sync iCal feeds and course imports, then ask again."
        )
    if corrected:
        note += (
            f" Stale dates corrected to this week ({mon}–{fri}); "
            f"today is {today.isoformat()}."
        )
    return {
        "events": events_out,
        "count": len(events_out),
        "start_date": start_iso,
        "end_date": end_iso,
        "today": today.isoformat(),
        "dates_corrected": corrected,
        "note": note,
    }


def list_tasks_for_range(due_start: str, due_end: str) -> dict:
    """List tasks from the Tasks tab (manual + cached Canvas) due in range."""
    start_iso, end_iso, corrected = sanitize_free_slot_range(due_start, due_end)
    start_d = _parse_date_bound(start_iso, end_of_day=False).date()
    end_d = _parse_date_bound(end_iso, end_of_day=True).date()

    tasks_out: list[dict] = []
    for raw in get_tasks():
        if not isinstance(raw, dict):
            continue
        if raw.get("is_completed"):
            continue
        due_d = _task_local_due_date(raw)
        if due_d is None or due_d < start_d or due_d > end_d:
            continue
        try:
            due = _parse_iso_datetime(raw.get("due_date"))
        except (ValueError, TypeError):
            continue
        t = _task_with_display_label(raw)
        t["due_date"] = due.isoformat()
        if due_d:
            t["local_due_date"] = due_d.isoformat()
        due_label = _as_str(raw.get("due_label")).strip()
        if due_label:
            t["due_label"] = due_label
        else:
            at_midnight = due.hour == 0 and due.minute == 0
            t["due_label"] = (
                _format_date_short(due)
                if at_midnight
                else f"{_format_date_short(due)} · {format_local_time(due)}"
            )
        tasks_out.append(t)
    tasks_out.sort(key=lambda t: t.get("due_date", ""))

    today = effective_today()
    mon, fri = week_range_mon_fri(today)
    if tasks_out:
        note = (
            f"{len(tasks_out)} task(s) from the Tasks tab (manual + cached Canvas). "
            "Use get_assignments for a live Canvas sync."
        )
    else:
        note = (
            "No tasks due in this range were sent from the app. "
            "Open Tasks to add items or sync Canvas, then ask again."
        )
    if corrected:
        note += (
            f" Stale dates corrected to this week ({mon}–{fri}); "
            f"today is {today.isoformat()}."
        )
    return {
        "tasks": tasks_out,
        "count": len(tasks_out),
        "due_start": start_iso,
        "due_end": end_iso,
        "today": today.isoformat(),
        "dates_corrected": corrected,
        "note": note,
    }


def _calendar_fixed_events() -> list:
    from app.services.scheduler_service import FixedEvent

    fixed: list[FixedEvent] = []
    for raw in get_calendar_events():
        if not isinstance(raw, dict):
            continue
        row = _parse_busy_event(raw)
        if row:
            bs, be, _ = row
            fixed.append(FixedEvent(start=bs, end=be))
    return fixed


def propose_schedule_change(
    task_name: object,
    hours: object,
    deadline: object,
    *,
    estimated_minutes: int | None = None,
) -> dict:
    """Propose proportional study blocks without writing to the calendar."""
    deadline_str = _as_str(deadline).strip()
    if not deadline_str:
        return {"proposal": [], "message": "A deadline date is required."}
    try:
        due = _parse_iso_datetime(deadline_str)
    except (ValueError, TypeError) as e:
        return {"proposal": [], "message": f"Could not parse deadline: {e}"}

    if estimated_minutes is not None:
        try:
            minutes = max(15, int(estimated_minutes))
        except (TypeError, ValueError):
            minutes = 60
    else:
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
    window_start = effective_now()
    look_ahead = max(1, min(60, (due.date() - effective_today()).days + 1))
    fixed = _calendar_fixed_events()
    blocks = service.suggest_task_sessions(
        task,
        fixed_events=fixed,
        look_ahead_days=look_ahead,
        window_start=window_start,
    )
    if not blocks:
        return {
            "proposal": [],
            "message": (
                f"Could not place {minutes} min for “{task_name}” before {deadline}. "
                "Try a later deadline, shorter duration, or fewer calendar conflicts."
            ),
        }
    proposal = [
        {
            "task_title": b.task_title,
            "start_time": b.start.isoformat(),
            "end_time": b.end.isoformat(),
            "duration_minutes": int((b.end - b.start).total_seconds() // 60),
            "is_ai_generated": True,
            "written_to_calendar": False,
        }
        for b in blocks
    ]
    session_note = (
        f"Split into {len(blocks)} session(s) sized by estimated duration "
        f"({minutes} min total), avoiding calendar busy times."
        if len(blocks) > 1
        else f"One {minutes}-minute block, avoiding calendar busy times."
    )
    return {
        "proposal": proposal,
        "total_estimated_minutes": minutes,
        "session_count": len(blocks),
        "message": f"Proposal only — not saved to your calendar yet. {session_note}",
    }
