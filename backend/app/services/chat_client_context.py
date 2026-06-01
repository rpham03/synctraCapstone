# Per-request calendar events and tasks sent from the Flutter app.
from __future__ import annotations

import contextvars
from typing import Any

_calendar_events: contextvars.ContextVar[list[dict[str, Any]] | None] = (
    contextvars.ContextVar("chat_calendar_events", default=None)
)
_tasks: contextvars.ContextVar[list[dict[str, Any]] | None] = contextvars.ContextVar(
    "chat_tasks", default=None
)


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


def clear_client_context() -> None:
    _calendar_events.set(None)
    _tasks.set(None)
