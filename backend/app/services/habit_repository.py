"""Durable habit storage (JSON). Swap for Supabase without changing service API."""
from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.models.habit_models import Habit, TimeRange

_backend_dir = Path(__file__).resolve().parents[2]
_store_path = _backend_dir / "data" / "habits.json"
_lock = threading.Lock()


def _ensure_store() -> None:
    _store_path.parent.mkdir(parents=True, exist_ok=True)
    if not _store_path.exists():
        _store_path.write_text("{}", encoding="utf-8")


def _load_all() -> Dict[str, List[dict]]:
    _ensure_store()
    raw = _store_path.read_text(encoding="utf-8").strip()
    if not raw:
        return {}
    return json.loads(raw)


def _save_all(data: Dict[str, List[dict]]) -> None:
    _ensure_store()
    _store_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _parse_time_ranges(raw: dict) -> Dict[int, List[TimeRange]]:
    out: Dict[int, List[TimeRange]] = {}
    for day_key, ranges in (raw or {}).items():
        day = int(day_key)
        parsed: List[TimeRange] = []
        for r in ranges:
            parsed.append(
                TimeRange(
                    start_minutes=_clock_to_minutes(r["start"]),
                    end_minutes=_clock_to_minutes(r["end"]),
                )
            )
        out[day] = parsed
    return out


def _serialize_time_ranges(ranges: Dict[int, List[TimeRange]]) -> dict:
    return {
        str(day): [
            {
                "start": _minutes_to_clock(tr.start_minutes),
                "end": _minutes_to_clock(tr.end_minutes),
            }
            for tr in day_ranges
        ]
        for day, day_ranges in ranges.items()
    }


def _clock_to_minutes(value: str) -> int:
    text = (value or "").strip().lower().replace(".", "")
    meridiem = ""
    if text.endswith("am") or text.endswith("pm"):
        meridiem = text[-2:]
        text = text[:-2].strip()
    else:
        parts = text.split()
        if len(parts) >= 2 and parts[-1] in ("am", "pm"):
            meridiem = parts[-1]
            text = parts[0]
    hour_str, _, minute_str = text.partition(":")
    hour = int(hour_str)
    minute = int(minute_str or 0)
    if meridiem.startswith("p") and hour != 12:
        hour += 12
    if meridiem.startswith("a") and hour == 12:
        hour = 0
    return hour * 60 + minute


def _minutes_to_clock(minutes: int) -> str:
    minutes = max(0, min(24 * 60 - 1, minutes))
    hour = minutes // 60
    minute = minutes % 60
    meridiem = "AM" if hour < 12 else "PM"
    display_hour = hour % 12 or 12
    if minute:
        return f"{display_hour}:{minute:02d}{meridiem.lower()}"
    return f"{display_hour}{meridiem.lower()}"


def _to_habit(row: dict) -> Habit:
    return Habit(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        duration_minutes=int(row["duration_minutes"]),
        frequency_per_week=int(row["frequency_per_week"]),
        preferred_days=[int(d) for d in row.get("preferred_days", [])],
        preferred_time_ranges=_parse_time_ranges(row.get("preferred_time_ranges", {})),
        priority=int(row["priority"]),
        is_active=bool(row.get("is_active", True)),
        created_at=datetime.fromisoformat(row["created_at"]),
        updated_at=datetime.fromisoformat(row["updated_at"]),
    )


def _from_habit(habit: Habit) -> dict:
    return {
        "id": habit.id,
        "user_id": habit.user_id,
        "title": habit.title,
        "duration_minutes": habit.duration_minutes,
        "frequency_per_week": habit.frequency_per_week,
        "preferred_days": habit.preferred_days,
        "preferred_time_ranges": _serialize_time_ranges(habit.preferred_time_ranges),
        "priority": habit.priority,
        "is_active": habit.is_active,
        "created_at": habit.created_at.isoformat(),
        "updated_at": habit.updated_at.isoformat(),
    }


class HabitRepository:
    def list_for_user(self, user_id: str) -> List[Habit]:
        with _lock:
            data = _load_all()
            return [_to_habit(row) for row in data.get(user_id, [])]

    def get(self, user_id: str, habit_id: str) -> Optional[Habit]:
        for habit in self.list_for_user(user_id):
            if habit.id == habit_id:
                return habit
        return None

    def create(self, user_id: str, payload: dict) -> Habit:
        now = datetime.utcnow()
        habit = Habit(
            id=str(uuid.uuid4()),
            user_id=user_id,
            title=payload["title"],
            duration_minutes=int(payload["duration_minutes"]),
            frequency_per_week=int(payload["frequency_per_week"]),
            preferred_days=[int(d) for d in payload.get("preferred_days", [])],
            preferred_time_ranges=_parse_time_ranges(payload.get("preferred_time_ranges", {})),
            priority=int(payload["priority"]),
            is_active=bool(payload.get("is_active", True)),
            created_at=now,
            updated_at=now,
        )
        with _lock:
            data = _load_all()
            rows = data.setdefault(user_id, [])
            rows.append(_from_habit(habit))
            _save_all(data)
        return habit

    def update(self, user_id: str, habit_id: str, payload: dict) -> Optional[Habit]:
        with _lock:
            data = _load_all()
            rows = data.get(user_id, [])
            for i, row in enumerate(rows):
                if row["id"] != habit_id:
                    continue
                row.update(
                    {
                        k: v
                        for k, v in payload.items()
                        if k
                        in {
                            "title",
                            "duration_minutes",
                            "frequency_per_week",
                            "preferred_days",
                            "priority",
                            "is_active",
                        }
                        and v is not None
                    }
                )
                if "preferred_time_ranges" in payload and payload["preferred_time_ranges"] is not None:
                    row["preferred_time_ranges"] = payload["preferred_time_ranges"]
                row["updated_at"] = datetime.utcnow().isoformat()
                rows[i] = row
                _save_all(data)
                return _to_habit(row)
        return None

    def delete(self, user_id: str, habit_id: str) -> bool:
        with _lock:
            data = _load_all()
            rows = data.get(user_id, [])
            new_rows = [r for r in rows if r["id"] != habit_id]
            if len(new_rows) == len(rows):
                return False
            data[user_id] = new_rows
            _save_all(data)
            return True
