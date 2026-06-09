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
    get_study_preferences,
    get_tasks,
    get_user_id,
)

_MAX_PROPOSALS = 12
_DEFAULT_TASK_MINUTES = 60
# Default cap when no Settings session length is provided. Long tasks are split
# into sessions of at most this many minutes, spread across different days
# (e.g. a 4h task -> two 2h sessions; 3h -> 90+90).
_MAX_SESSION_MINUTES = 120
_DEFAULT_BREAK_MINUTES = 15
# Used when the user hasn't set a Settings study window or a productive period.
_DEFAULT_WINDOW_START = "09:00"
_DEFAULT_WINDOW_END = "21:00"


def _split_minutes(total: int, cap: int = _MAX_SESSION_MINUTES) -> list[int]:
    """Split a task's total minutes into evenly-sized sessions of <= ``cap``."""
    total = max(int(total), 1)
    cap = max(int(cap), 15)
    if total <= cap:
        return [total]
    sessions = -(-total // cap)  # ceil
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


def _in_any_window(start_dt: datetime, windows: list[tuple[str, str]]) -> bool:
    for ws_str, we_str in windows:
        ws, we = _window_for(start_dt.date(), ws_str, we_str)
        if ws <= start_dt < we:
            return True
    return False


def _pretty_clock(hhmm: str) -> str:
    try:
        hour, minute = (int(x) for x in str(hhmm).split(":"))
    except (ValueError, TypeError):
        return str(hhmm)
    suffix = "AM" if hour < 12 else "PM"
    h12 = hour % 12 or 12
    return f"{h12}:{minute:02d} {suffix}" if minute else f"{h12} {suffix}"


def _proposal_signature(proposals: list[dict]) -> tuple:
    """Stable fingerprint of a proposal set (task/event + start + end times).

    Used by the router to guarantee "try again" yields a genuinely different
    arrangement and to detect when no alternative exists.
    """

    return tuple(
        sorted(
            (
                str(p.get("task_title") or p.get("replace_block_id") or ""),
                str(p.get("start_time") or ""),
                str(p.get("end_time") or ""),
            )
            for p in proposals
        )
    )


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
    break_minutes: int = _DEFAULT_BREAK_MINUTES,
) -> dict:
    """Return preview proposals placing flexible work inside the study window.

    The window, session length, and break come from the user's Settings
    (study_start/end, session length, break) when the client sent them this
    request; otherwise they fall back to the saved productive periods. With
    ``seed`` set, task order and slot choice are randomized so a "try again"
    produces a different arrangement. Blocks are never placed outside the
    window, long tasks are split using the configured session length, and a
    configured break is left after each placed session.
    """

    uid = user_id or get_user_id()
    prefs = productivity_preferences.get_preferences(uid)
    study = get_study_preferences()

    # Resolve the daily window(s), session cap, and break from whichever source
    # is configured. Settings (an explicit study window) wins over saved periods.
    if study and study.get("start") and study.get("end"):
        windows: list[tuple[str, str]] = [(study["start"], study["end"])]
        session_cap = int(study.get("session_minutes") or _MAX_SESSION_MINUTES)
        break_minutes = int(study.get("break_minutes") or break_minutes)
        window_label = f"{_pretty_clock(study['start'])}–{_pretty_clock(study['end'])}"
    elif prefs:
        windows = [(p["start"], p["end"]) for p in prefs]
        session_cap = _MAX_SESSION_MINUTES
        window_label = ", ".join(p["period"] for p in prefs)
    else:
        # No Settings window and no saved period — use a sensible daytime
        # default so a generic "suggest a schedule for my tasks" still works
        # (placed during the day with breaks, never overnight).
        windows = [(_DEFAULT_WINDOW_START, _DEFAULT_WINDOW_END)]
        session_cap = _MAX_SESSION_MINUTES
        window_label = (
            f"{_pretty_clock(_DEFAULT_WINDOW_START)}–{_pretty_clock(_DEFAULT_WINDOW_END)}"
        )
    session_cap = max(15, min(int(session_cap), 24 * 60))
    break_minutes = max(0, int(break_minutes))

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
            for ws_str, we_str in windows:
                ws, we = _window_for(day, ws_str, we_str)
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
        if _in_any_window(start, windows):
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
        sessions = _split_minutes(_task_minutes(task), session_cap)
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

    if not proposals:
        message = (
            f"I couldn't find open time in your {window_label} study window for any "
            "flexible work right now."
        )
    else:
        message = f"Here's a suggested schedule in your {window_label} study window:"
    return {
        "proposals": proposals,
        "message": message,
        "periods": [p["period"] for p in prefs],
        "window_label": window_label,
        "signature": _proposal_signature(proposals),
    }
