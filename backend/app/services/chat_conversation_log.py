"""Durable JSONL logging for user and assistant chat turns."""

from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config.settings import settings


_write_lock = threading.Lock()
_backend_dir = Path(__file__).resolve().parents[2]


def conversation_log_path() -> Path:
    """Return the configured path, resolving relative paths from backend/."""

    configured = (settings.chat_conversation_log_path or "").strip()
    path = Path(configured or "data/chat_conversations.jsonl").expanduser()
    return path if path.is_absolute() else _backend_dir / path


def append_conversation_turn(
    *,
    user_id: str,
    provider: str,
    user_message: str,
    assistant_reply: str,
    schedule_proposals: list[dict[str, Any]] | None = None,
    client_today: str | None = None,
    timezone_name: str | None = None,
) -> None:
    """Append one complete chat turn without storing calendar/task context."""

    if not settings.chat_conversation_log_enabled:
        return
    row = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
        "provider": provider,
        "user_message": user_message,
        "assistant_reply": assistant_reply,
        "schedule_proposals": schedule_proposals or [],
        "client_today": client_today or "",
        "timezone_name": timezone_name or "",
    }
    path = conversation_log_path()
    with _write_lock:
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        row,
                        ensure_ascii=False,
                        separators=(",", ":"),
                        default=str,
                    )
                    + "\n"
                )
        except OSError as exc:
            print(f"[chat-log] could not write {path}: {exc}", flush=True)
