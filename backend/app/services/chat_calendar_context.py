# Backward-compatible re-exports — use chat_client_context for new code.
from app.services.chat_client_context import (
    clear_client_context,
    get_calendar_events,
    get_tasks,
    set_calendar_events,
    set_tasks,
)

__all__ = [
    "clear_client_context",
    "get_calendar_events",
    "get_tasks",
    "set_calendar_events",
    "set_tasks",
]
