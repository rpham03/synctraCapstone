"""Suggest a schedule that places flexible work near preferred productive periods.

Reuses the deterministic classification (fixed events are busy and never moved)
and the existing busy/gap helpers. suggest_* only produces a preview; the router
requires the user to confirm before apply_* writes anything to the calendar.
"""

from __future__ import annotations

import random
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
# Long tasks are split into study sessions of at most this many minutes, spread
# across different days (e.g. a 4h task -> two 2h sessions; 3h -> 90+90).
_MAX_SESSION_MINUTES = 120


def _split_minutes(total: int) -> list[int]:
    """Split a task's total minutes into evenly-sized sessions of <= 2 hours."""
    total = max(int(total), 1)
    if total <= _MAX_SESSION_MINUTES:
        return [total]
    sessions = -(-total // _MAX_SESSION_MINUTES)  # ceil
    base, remainder = divmod(total, sessions)
    return [base + (1 if i < remainder else 0) for i in range(sessions)]


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


def suggest_preference_schedule(
    *,
    user_id: str | None = None,
    days_ahead: int = 7,
    seed: int | None = None,
    break_minutes: int = 15,
) -> dict:
    """Return preview proposals placing flexible work near preferred periods.

    With ``seed`` set, task order and slot choice are randomized so a "try again"
    produces a different arrangement. ``break_minutes`` keeps a gap after each
    placed study session so they aren't scheduled back to back.
    """

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
    placed: list[tuple[datetime, datetime]] = list(busy)  # fixed events only
    rng = random.Random(seed) if seed is not None else None
    break_delta = timedelta(minutes=max(0, break_minutes))

    def reserve(start: datetime, end: datetime) -> None:
        # Reserve the session plus a trailing break so the next one isn't adjacent.
        placed.append((start, end + break_delta))

    if rng is not None:
        rng.shuffle(flexible_events)

    def find_slot(
        duration: timedelta, deadline: datetime | None, *, start_offset: int = 0
    ) -> tuple[datetime, datetime] | None:
        candidates: list[tuple[datetime, datetime]] = []
        for offset in range(start_offset, days_ahead + 1):
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
                        if rng is None:
                            return gap_start, cand_end  # earliest — deterministic
                        candidates.append((gap_start, cand_end))
        return rng.choice(candidates) if (rng is not None and candidates) else None

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
            reserve(start, end)  # already good — keep it as busy
            continue
        slot = find_slot(duration, None)
        if slot:
            reserve(slot[0], slot[1])
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
            reserve(start, end)
        if len(proposals) >= _MAX_PROPOSALS:
            break

    # 2) Flexible tasks: split long ones into <=2h sessions across the week.
    tasks = list(get_tasks())
    if rng is not None:
        rng.shuffle(tasks)
    for task in tasks:
        if len(proposals) >= _MAX_PROPOSALS:
            break
        if task.get("is_completed"):
            continue
        deadline = _task_deadline(task)
        sessions = _split_minutes(_task_minutes(task))
        title = str(task.get("title") or "Study block")
        next_offset = 0
        for index, minutes in enumerate(sessions):
            if len(proposals) >= _MAX_PROPOSALS:
                break
            duration = timedelta(minutes=minutes)
            # Prefer a later day so the sessions spread out; if nothing's left
            # before the deadline, fall back to any open day.
            slot = find_slot(duration, deadline, start_offset=next_offset)
            if slot is None and next_offset > 0:
                slot = find_slot(duration, deadline)
            if slot is None:
                break
            reserve(slot[0], slot[1])
            label = title if len(sessions) == 1 else f"{title} ({index + 1}/{len(sessions)})"
            proposals.append(
                {
                    "task_title": label,
                    "start_time": slot[0].isoformat(),
                    "end_time": slot[1].isoformat(),
                    "duration_minutes": minutes,
                    "is_ai_generated": True,
                    "written_to_calendar": False,
                }
            )
            next_offset = (slot[0].date() - today).days + 1

    period_label = ", ".join(p["period"] for p in prefs)
    if not proposals:
        message = (
            f"I couldn't find open time near your {period_label} preference for any "
            "flexible work right now."
        )
    else:
        message = f"Here's a suggested schedule near your {period_label} preference:"
    return {"proposals": proposals, "message": message, "periods": [p["period"] for p in prefs]}
