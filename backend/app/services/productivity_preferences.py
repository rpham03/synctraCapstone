"""Per-user productivity preferences (preferred productive periods).

A preference is a named period (morning/afternoon/evening/night) with a clock
range. Defaults are used unless the user gives explicit times. Stored durably as
JSON per user, mirroring the chat conversation log's backend/data pattern.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

_backend_dir = Path(__file__).resolve().parents[2]
_store_path = _backend_dir / "data" / "productivity_preferences.json"
_lock = threading.Lock()

# Period -> (default start, default end) as "HH:MM" (24h). Night ends at midnight.
DEFAULT_RANGES: dict[str, tuple[str, str]] = {
    "morning": ("06:00", "12:00"),
    "afternoon": ("12:00", "17:00"),
    "evening": ("17:00", "21:00"),
    "night": ("21:00", "00:00"),
}
PERIODS = tuple(DEFAULT_RANGES)

# Natural-language words that map to a canonical period.
_PERIOD_WORDS: list[tuple[str, str]] = [
    (r"\b(?:early\s+)?mornings?\b", "morning"),
    (r"\bafternoons?\b", "afternoon"),
    (r"\bevenings?\b", "evening"),
    (r"\b(?:late\s+)?nights?\b", "night"),
]


def detect_periods(text: str) -> list[str]:
    """Return canonical periods named in the text, in first-seen order."""

    lower = (text or "").lower()
    hits: list[tuple[str, int]] = []
    seen: set[str] = set()
    for pattern, period in _PERIOD_WORDS:
        match = re.search(pattern, lower)
        if match and period not in seen:
            seen.add(period)
            hits.append((period, match.start()))
    # Order by where each period appeared in the message.
    return [period for period, _ in sorted(hits, key=lambda x: x[1])]


def _normalize_clock(value: object) -> str | None:
    """Parse "8pm", "8:30 pm", "20:00", "20" -> "HH:MM", else None."""

    text = str(value or "").strip().lower()
    if not text:
        return None
    match = re.match(r"^(\d{1,2})(?::(\d{2}))?\s*(am|pm|a\.m\.|p\.m\.)?$", text)
    if not match:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    ampm = (match.group(3) or "").replace(".", "")
    if ampm:
        if hour < 1 or hour > 12 or minute > 59:
            return None
        if ampm.startswith("p") and hour != 12:
            hour += 12
        if ampm.startswith("a") and hour == 12:
            hour = 0
    elif hour > 23 or minute > 59:
        return None
    return f"{hour:02d}:{minute:02d}"


def _read_all() -> dict[str, Any]:
    try:
        return json.loads(_store_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_all(data: dict[str, Any]) -> None:
    with _lock:
        try:
            _store_path.parent.mkdir(parents=True, exist_ok=True)
            _store_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except OSError as exc:
            print(f"[preferences] could not write {_store_path}: {exc}", flush=True)


def get_preferences(user_id: str) -> list[dict[str, str]]:
    """Return the user's saved preferences: [{period, start, end}, ...]."""

    raw = _read_all().get(user_id) or []
    out: list[dict[str, str]] = []
    for item in raw:
        if isinstance(item, dict) and item.get("period") in DEFAULT_RANGES:
            out.append(
                {
                    "period": item["period"],
                    "start": str(item.get("start") or DEFAULT_RANGES[item["period"]][0]),
                    "end": str(item.get("end") or DEFAULT_RANGES[item["period"]][1]),
                }
            )
    return out


def set_preferences(
    user_id: str,
    periods: list[str],
    *,
    start: object = "",
    end: object = "",
) -> list[dict[str, str]]:
    """Add/replace the given periods for the user (idempotent per period)."""

    valid = [p for p in periods if p in DEFAULT_RANGES]
    if not valid:
        return get_preferences(user_id)

    custom_start = _normalize_clock(start)
    custom_end = _normalize_clock(end)

    data = _read_all()
    existing = {p["period"]: p for p in get_preferences(user_id)}
    for period in valid:
        d_start, d_end = DEFAULT_RANGES[period]
        existing[period] = {
            "period": period,
            "start": custom_start or d_start,
            "end": custom_end or d_end,
        }
    data[user_id] = [existing[p] for p in DEFAULT_RANGES if p in existing]
    _write_all(data)
    return get_preferences(user_id)


def remove_preferences(user_id: str, periods: list[str] | None = None) -> list[dict[str, str]]:
    """Remove specific periods, or all when periods is None/empty."""

    data = _read_all()
    if not periods:
        data.pop(user_id, None)
        _write_all(data)
        return []
    remaining = [p for p in get_preferences(user_id) if p["period"] not in set(periods)]
    if remaining:
        data[user_id] = remaining
    else:
        data.pop(user_id, None)
    _write_all(data)
    return remaining


def clear_user(user_id: str) -> None:
    """Test helper — drop a user's stored preferences."""
    data = _read_all()
    if data.pop(user_id, None) is not None:
        _write_all(data)
