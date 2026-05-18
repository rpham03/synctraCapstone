# Per-request calendar busy times for the chat agent (from the mobile app).
from __future__ import annotations

import contextvars
from typing import Any

_calendar_events: contextvars.ContextVar[list[dict[str, Any]] | None] = (
    contextvars.ContextVar("chat_calendar_events", default=None)
)


def set_calendar_events(events: list[dict[str, Any]] | None) -> None:
    _calendar_events.set(events)


def get_calendar_events() -> list[dict[str, Any]]:
    raw = _calendar_events.get()
    if not raw:
        return []
    return [e for e in raw if isinstance(e, dict)]
