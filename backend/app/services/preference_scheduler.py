"""Suggest a schedule that places flexible work near preferred productive periods.

Reuses the deterministic classification (fixed events are busy and never moved)
and the existing busy/gap helpers. suggest_* only produces a preview; the router
requires the user to confirm before apply_* writes anything to the calendar.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta

from app.services import event_classification, productivity_preferences
from app.services.chat_agent_tools import (
    _gaps_between_busy,
    _parse_busy_event,
    _parse_iso_datetime,
)
from app.services.chat_client_context import (
    effective_now,
    effective_today,
    get_calendar_events,
    get_tasks,
    get_user_id,
)

_MAX_PROPOSALS = 12
_DEFAULT_TASK_MINUTES = 60


def _window_for(day, start_hhmm: str, end_hhmm: str) -> tuple[datetime, datetime]:
    sh, sm = (int(x) for x in start_hhmm.split(":"))
    eh, em = (int(x) for x in end_hhmm.split(":"))
    start = datetime.combine(day, time(sh, sm))
    # "00:00" or any end <= start means the window runs to the next midnight.
    if (eh, em) <= (sh, sm):
        end = datetime.combine(day, time(0, 0)) + timedelta(days=1)
    else:
        end = datetime.combine(day, time(eh, em))
    return start, end


def _in_any_window(start_dt: datetime, prefs: list[dict]) -> bool:
    for pref in prefs:
        ws, we = _window_for(start_dt.date(), pref["start"], pref["end"])
        if ws <= start_dt < we:
            return True
    return False


def _task_minutes(task: dict) -> int:
    raw = task.get("estimated_minutes")
    try:
        minutes = int(raw)
    except (TypeError, ValueError):
        minutes = 0
    return minutes if minutes > 0 else _DEFAULT_TASK_MINUTES


def _task_deadline(task: dict) -> datetime | None:
    for key in ("due_date", "local_due_date"):
        try:
            return _parse_iso_datetime(task.get(key))
        except (ValueError, TypeError):
            continue
    return None


def suggest_preference_schedule(*, user_id: str | None = None, days_ahead: int = 7) -> dict:
    """Return preview proposals placing flexible work near preferred periods."""

    uid = user_id or get_user_id()
    prefs = productivity_preferences.get_preferences(uid)
    if not prefs:
        return {
            "proposals": [],
            "message": "Tell me when you're most productive first (e.g. \"I'm productive at night\").",
        }

    events = get_calendar_events()
    classified = event_classification.classify_all_calendar_events(events, user_id=uid)["events"]
    by_id = {c["event_id"]: c for c in classified}

    busy: list[tuple[datetime, datetime]] = []
    flexible_events: list[dict] = []
    for raw in events:
        if not isinstance(raw, dict):
            continue
        row = _parse_busy_event(raw)
        cls = by_id.get(str(raw.get("id") or ""))
        flexibility = cls["fixed_or_flexible"] if cls else "fixed"
        if flexibility == "flexible":
            if row:
                flexible_events.append(raw)
        elif row:  # fixed and uncertain stay put / count as busy
            busy.append((row[0], row[1]))

    today = effective_today()
    now = effective_now()
    placed: list[tuple[datetime, datetime]] = list(busy)

    def find_slot(duration: timedelta, deadline: datetime | None) -> tuple[datetime, datetime] | None:
        for offset in range(days_ahead + 1):
            day = today + timedelta(days=offset)
            for pref in prefs:
                ws, we = _window_for(day, pref["start"], pref["end"])
                ws = max(ws, now)  # never schedule in the past
                if we <= ws:
                    continue
                for gap_start, gap_end in _gaps_between_busy(
                    ws, we, placed, min_duration=duration
                ):
                    cand_end = gap_start + duration
                    if cand_end <= gap_end and (deadline is None or cand_end <= deadline):
                        return gap_start, cand_end
        return None

    proposals: list[dict] = []

    # 1) Relocate flexible events that aren't already in a preferred window.
    for raw in flexible_events:
        try:
            start = _parse_iso_datetime(raw.get("start_time"))
            end = _parse_iso_datetime(raw.get("end_time"))
        except (ValueError, TypeError):
            continue
        duration = end - start
        if _in_any_window(start, prefs):
            placed.append((start, end))  # already good — keep it as busy
            continue
        slot = find_slot(duration, None)
        if slot:
            placed.append(slot)
            proposals.append(
                {
                    "task_title": str(raw.get("title") or "Study block"),
                    "start_time": slot[0].isoformat(),
                    "end_time": slot[1].isoformat(),
                    "duration_minutes": int(duration.total_seconds() // 60),
                    "is_ai_generated": bool(raw.get("is_ai_generated", True)),
                    "written_to_calendar": False,
                    "replace_block_id": str(raw.get("id") or "").strip(),
                }
            )
        else:
            placed.append((start, end))
        if len(proposals) >= _MAX_PROPOSALS:
            break

    # 2) New blocks for flexible tasks before their deadline.
    for task in get_tasks():
        if len(proposals) >= _MAX_PROPOSALS:
            break
        if task.get("is_completed"):
            continue
        minutes = _task_minutes(task)
        slot = find_slot(timedelta(minutes=minutes), _task_deadline(task))
        if not slot:
            continue
        placed.append(slot)
        proposals.append(
            {
                "task_title": str(task.get("title") or "Study block"),
                "start_time": slot[0].isoformat(),
                "end_time": slot[1].isoformat(),
                "duration_minutes": minutes,
                "is_ai_generated": True,
                "written_to_calendar": False,
            }
        )

    period_label = ", ".join(p["period"] for p in prefs)
    if not proposals:
        message = (
            f"I couldn't find open time near your {period_label} preference for any "
            "flexible work right now."
        )
    else:
        message = f"Here's a suggested schedule near your {period_label} preference:"
    return {"proposals": proposals, "message": message, "periods": [p["period"] for p in prefs]}
