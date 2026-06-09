# Per-request calendar events and tasks sent from the Flutter app.
from __future__ import annotations

import contextvars
from datetime import date, datetime, timedelta, timezone
from typing import Any

_calendar_events: contextvars.ContextVar[list[dict[str, Any]] | None] = (
    contextvars.ContextVar("chat_calendar_events", default=None)
)
_tasks: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar(
    "chat_tasks", default=None
)
_client_today: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "chat_client_today", default=None
)
_timezone_offset: contextvars.ContextVar[int | None] = contextvars.ContextVar(
    "chat_timezone_offset_minutes", default=None
)
_timezone_name: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "chat_timezone_name", default=None
)
_schedule_proposals: contextvars.ContextVar[list[dict[str, Any]] | None] = (
    contextvars.ContextVar("chat_schedule_proposals", default=None)
)
_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "chat_user_id", default=None
)
_study_preferences: contextvars.ContextVar[dict[str, Any] | None] = (
    contextvars.ContextVar("chat_study_preferences", default=None)
)


def set_study_preferences(value: dict[str, Any] | None) -> None:
    """Latest Settings-screen study window/session/break for this request.

    Shape: {"start": "HH:MM", "end": "HH:MM", "session_minutes": int,
    "break_minutes": int}. Any missing/invalid key is dropped so the scheduler
    falls back to its defaults rather than crashing.
    """

    if not isinstance(value, dict):
        _study_preferences.set(None)
        return
    cleaned: dict[str, Any] = {}
    start = _normalize_hhmm(value.get("start"))
    end = _normalize_hhmm(value.get("end"))
    if start and end:
        cleaned["start"] = start
        cleaned["end"] = end
    for key in ("session_minutes", "break_minutes"):
        try:
            minutes = int(value.get(key))
        except (TypeError, ValueError):
            continue
        if minutes > 0:
            cleaned[key] = minutes
    _study_preferences.set(cleaned or None)


def get_study_preferences() -> dict[str, Any] | None:
    raw = _study_preferences.get()
    return raw if isinstance(raw, dict) and raw else None


def _normalize_hhmm(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parts = text.split(":")
        hour = int(parts[0])
        minute = int(parts[1]) if len(parts) > 1 else 0
    except (ValueError, IndexError):
        return ""
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return ""
    return f"{hour:02d}:{minute:02d}"


def set_user_id(value: str | None) -> None:
    _user_id.set((value or "").strip() or None)


def get_user_id() -> str:
    return _user_id.get() or "app-user"


def set_calendar_events(events: list[dict[str, Any]] | None) -> None:
    _calendar_events.set(events)


def get_calendar_events() -> list[dict[str, Any]]:
    raw = _calendar_events.get()
    if not raw:
        return []
    return [e for e in raw if isinstance(e, dict)]


def set_tasks(tasks: list[dict[str, Any]] | None) -> None:
    _tasks.set(tasks)


def get_tasks() -> list[dict[str, Any]]:
    raw = _tasks.get()
    if not raw:
        return []
    return [t for t in raw if isinstance(t, dict)]


def set_client_today(value: str | None) -> None:
    _client_today.set(value)


def set_timezone_offset_minutes(value: int | None) -> None:
    _timezone_offset.set(value)


def get_timezone_offset_minutes() -> int | None:
    return _timezone_offset.get()


def set_timezone_name(value: str | None) -> None:
    _timezone_name.set((value or "").strip() or None)


def get_timezone_name() -> str | None:
    return _timezone_name.get()


def client_timezone_label() -> str:
    name = get_timezone_name()
    if name:
        return name
    offset = get_timezone_offset_minutes()
    if offset is not None:
        hours = offset // 60
        sign = "+" if hours >= 0 else ""
        return f"UTC{sign}{hours}"
    return "local time"


def effective_today() -> date:
    from app.services.chat_agent_tools import today_local

    raw = _client_today.get()
    if raw:
        try:
            return date.fromisoformat(str(raw).strip()[:10])
        except ValueError:
            pass
    return today_local()


def effective_now() -> datetime:
    """Current client-local wall time, falling back to server local time."""
    offset = get_timezone_offset_minutes()
    if offset is not None:
        utc_now = datetime.now(timezone.utc).replace(tzinfo=None)
        return utc_now + timedelta(minutes=offset)

    raw = _client_today.get()
    if raw:
        try:
            today = date.fromisoformat(str(raw).strip()[:10])
            server_now = datetime.now()
            return datetime.combine(today, server_now.time()).replace(microsecond=0)
        except ValueError:
            pass
    return datetime.now().replace(microsecond=0)


def append_schedule_proposals(items: list[dict[str, Any]]) -> None:
    if not items:
        return
    current = list(_schedule_proposals.get() or [])
    current.extend(items)
    _schedule_proposals.set(current)


def get_schedule_proposals() -> list[dict[str, Any]]:
    raw = _schedule_proposals.get()
    if not raw:
        return []
    return [p for p in raw if isinstance(p, dict)]


def clear_client_context() -> None:
    _calendar_events.set(None)
    _tasks.set(None)
    _client_today.set(None)
    _timezone_offset.set(None)
    _timezone_name.set(None)
    _schedule_proposals.set(None)
    _user_id.set(None)
    _study_preferences.set(None)
