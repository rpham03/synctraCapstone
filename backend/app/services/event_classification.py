"""Classify calendar events as fixed or flexible.

Deterministic, safety-first rules decide fixed vs flexible and the event type.
Results are cached per user by a content hash so unchanged events are not
re-evaluated, and explicit user overrides always win and are never replaced by a
later (re)classification. An optional AI agent may later resolve only the
uncertain remainder — deterministic rules always override unsafe AI results.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from pathlib import Path
from typing import Any

import httpx

from app.core.config.settings import settings

_backend_dir = Path(__file__).resolve().parents[2]
_store_path = _backend_dir / "data" / "event_classifications.json"
_lock = threading.Lock()

# Sources whose events are mirrors of an external/authoritative calendar — never
# flexible, never movable.
FIXED_SOURCES = {"course", "canvas", "ical", "google_calendar"}
# User/AI work that can be scheduled around fixed commitments.
FLEXIBLE_SOURCES = {"study_block", "manual_task"}

# Event-type detection from the title (first match wins). Used for reporting and
# to resolve fixed/flexible when the source alone is not decisive.
_TYPE_PATTERNS: list[tuple[str, str]] = [
    ("exam", r"\b(?:exam|midterm|final|quiz|test)\b"),
    ("class", r"\b(?:lecture|lab|section|class|discussion|seminar|recitation)\b"),
    ("meeting", r"\b(?:meeting|standup|stand-up|sync|1:1|one[ -]on[ -]one|interview)\b"),
    ("appointment", r"\b(?:appointment|appt|dentist|doctor|clinic|haircut)\b"),
    ("work_shift", r"\b(?:shift|work)\b"),
    ("homework", r"\b(?:homework|hw|assignment|problem set|pset|essay|paper|reading|read|project)\b"),
    ("study_session", r"\b(?:study|review|prep|practice|revise)\b"),
    ("personal", r"\b(?:gym|workout|lunch|dinner|break|gaming|game|hangout|call)\b"),
]
_FIXED_TYPES = {"exam", "class", "meeting", "appointment", "work_shift"}
_FLEXIBLE_TYPES = {"homework", "study_session", "task"}

_VALID_OVERRIDES = {"fixed", "flexible"}


def _as_str(value: object) -> str:
    return "" if value is None else str(value)


def content_hash(event: dict) -> str:
    """Stable hash of the fields that affect classification."""

    key = "|".join(
        _as_str(event.get(field)).strip().lower()
        for field in ("id", "title", "source", "start_time", "end_time")
    )
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def _event_type(title: str, source: str) -> str:
    lower = title.lower()
    for etype, pattern in _TYPE_PATTERNS:
        if re.search(pattern, lower):
            return etype
    if source == "study_block":
        return "study_session"
    if source == "manual_task":
        return "task"
    if source in FIXED_SOURCES:
        return "class"
    return "unknown"


def classify_deterministic(event: dict) -> dict:
    """Apply safety-first rules. fixed_or_flexible may be 'uncertain'."""

    event_id = _as_str(event.get("id")).strip()
    title = _as_str(event.get("title")).strip() or "Event"
    source = _as_str(event.get("source")).strip().lower()
    etype = _event_type(title, source)

    if source in FIXED_SOURCES:
        fx, conf, reason = "fixed", 1.0, "Imported/external event — always fixed."
    elif source == "study_block":
        fx, conf, reason = "flexible", 0.95, "AI-generated study block."
    elif source == "manual_task":
        fx, conf, reason = "flexible", 0.9, "Task to work on — flexible."
    elif source == "manual":
        fx, conf, reason = "fixed", 0.85, "Manual calendar event — fixed unless marked flexible."
    elif etype in _FIXED_TYPES:
        fx, conf, reason = "fixed", 0.8, f"{etype.replace('_', ' ')} — fixed commitment."
    elif etype in _FLEXIBLE_TYPES:
        fx, conf, reason = "flexible", 0.8, f"{etype.replace('_', ' ')} — flexible work."
    else:
        fx, conf, reason = "uncertain", 0.0, "Could not determine fixed vs flexible."

    return {
        "event_id": event_id,
        "event_name": title,
        "event_type": etype,
        "fixed_or_flexible": fx,
        "confidence": conf,
        "reason": reason,
        "classified_by": "rule",
    }


# ---- per-user persistence -------------------------------------------------

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
            print(f"[classify] could not write {_store_path}: {exc}", flush=True)


def _user_record(data: dict[str, Any], user_id: str) -> dict[str, Any]:
    rec = data.get(user_id)
    if not isinstance(rec, dict):
        rec = {}
    rec.setdefault("cache", {})
    rec.setdefault("overrides", {})
    return rec


def get_override(user_id: str, event_id: str) -> str | None:
    rec = _read_all().get(user_id)
    if isinstance(rec, dict):
        value = rec.get("overrides", {}).get(event_id)
        if value in _VALID_OVERRIDES:
            return value
    return None


def set_override(user_id: str, event_id: str, flexibility: str) -> bool:
    """Persist an explicit user override. Returns True when stored."""

    flexibility = (flexibility or "").strip().lower()
    if not event_id or flexibility not in _VALID_OVERRIDES:
        return False
    data = _read_all()
    rec = _user_record(data, user_id)
    rec["overrides"][event_id] = flexibility
    data[user_id] = rec
    _write_all(data)
    return True


def clear_user(user_id: str) -> None:
    """Test helper — drop a user's cache and overrides."""
    data = _read_all()
    if data.pop(user_id, None) is not None:
        _write_all(data)


def _apply_override(result: dict, flexibility: str) -> dict:
    out = dict(result)
    out["fixed_or_flexible"] = flexibility
    out["confidence"] = 1.0
    out["reason"] = "User override."
    out["classified_by"] = "override"
    return out


def classify_all_calendar_events(
    events: list[dict],
    *,
    user_id: str,
) -> dict:
    """Classify every event: overrides win, then cache, then deterministic rules.

    Returns the per-event results plus counts of fixed/flexible/uncertain/cached/
    newly classified. Caching keys on a content hash so unchanged events are not
    re-evaluated; changed events (new hash) are reclassified.
    """

    data = _read_all()
    rec = _user_record(data, user_id)
    cache: dict[str, Any] = rec["cache"]
    overrides: dict[str, Any] = rec["overrides"]

    results: list[dict] = []
    counts = {"fixed": 0, "flexible": 0, "uncertain": 0, "cached": 0, "newly_classified": 0}
    dirty = False

    for event in events:
        if not isinstance(event, dict):
            continue
        event_id = _as_str(event.get("id")).strip()
        h = content_hash(event)

        override = overrides.get(event_id) if event_id else None
        if override in _VALID_OVERRIDES:
            result = _apply_override(classify_deterministic(event), override)
        elif h in cache:
            result = dict(cache[h])
            result["classified_by"] = "cache"
            counts["cached"] += 1
        else:
            result = classify_deterministic(event)
            # Only cache a resolved verdict — leave uncertain events uncached so
            # a later run (e.g. once an AI agent is reachable) can retry them.
            if result["fixed_or_flexible"] != "uncertain":
                cache[h] = {k: v for k, v in result.items() if k != "classified_by"}
                dirty = True
            counts["newly_classified"] += 1

        fx = result.get("fixed_or_flexible")
        if fx in counts:
            counts[fx] += 1
        results.append(result)

    if dirty:
        data[user_id] = rec
        _write_all(data)

    return {"events": results, "counts": counts}


# ---- optional AI assist for the uncertain remainder ------------------------

_AI_EVENT_TYPES = (
    "class, lecture, lab, exam, quiz, meeting, appointment, homework, "
    "assignment, study_session, personal, work_shift, task, unknown"
)


def _ai_host() -> str:
    return (
        os.getenv("COLAB_AI_AGENT_HOST")
        or settings.colab_ai_agent_host
        or os.getenv("COLAB_COURSE_IMPORT_HOST")
        or settings.colab_course_import_host
        or os.getenv("OLLAMA_HOST")
        or os.getenv("COLAB_NLP_ROUTER_HOST")
        or settings.colab_nlp_router_host
        or ""
    ).strip().rstrip("/")


def _build_ai_prompt(payload: list[dict]) -> str:
    lines = [
        "Classify each calendar event as fixed or flexible.",
        "Fixed = a required time the user cannot move (classes, exams, meetings, "
        "appointments, work shifts). Flexible = work the user chooses when to do "
        "(homework, assignments, study sessions, personal tasks).",
        f"event_type must be one of: {_AI_EVENT_TYPES}.",
        'Return ONLY JSON: {"events":[{"event_id":"...","event_name":"...",'
        '"event_type":"...","fixed_or_flexible":"fixed|flexible",'
        '"confidence":0.0,"reason":"..."}]}',
        "Events:",
    ]
    for item in payload:
        lines.append(
            f'- event_id={item["event_id"]} name="{item["event_name"]}" '
            f'guess_type={item["event_type"]}'
        )
    return "\n".join(lines)


def _parse_ai_json(text: str) -> list[dict]:
    """Pull the events array out of the agent's reply (tolerant of prose around it)."""

    if not text:
        return []
    try:
        data = json.loads(text)
    except ValueError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            return []
        try:
            data = json.loads(match.group(0))
        except ValueError:
            return []
    events = data.get("events") if isinstance(data, dict) else None
    return [e for e in events if isinstance(e, dict)] if isinstance(events, list) else []


async def _call_ai_agent(host: str, payload: list[dict]) -> list[dict]:
    """POST the uncertain events to the Qwen agent and parse its JSON reply."""

    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            f"{host}/api/generate",
            json={
                "prompt": _build_ai_prompt(payload),
                "stream": False,
                "options": {"syntra_mode": "ai_agent", "temperature": 0.1},
            },
            headers={"Accept": "application/json", "ngrok-skip-browser-warning": "true"},
        )
        response.raise_for_status()
        body = response.json()
    text = str(body.get("response") or body.get("assistant_message") or "")
    return _parse_ai_json(text)


async def classify_all_calendar_events_with_ai(
    events: list[dict],
    *,
    user_id: str,
) -> dict:
    """Deterministic classification, then ask the AI agent for the uncertain ones.

    Only the uncertain events' id/name/guessed-type are sent — never private
    descriptions. Deterministic safety rules still override the AI (it can never
    turn a fixed event flexible). Failures are swallowed so classification (and
    the rest of the app) keep working.
    """

    base = classify_all_calendar_events(events, user_id=user_id)
    uncertain = [e for e in base["events"] if e.get("fixed_or_flexible") == "uncertain"]
    host = _ai_host()
    if not uncertain or not host:
        return base

    by_id = {
        _as_str(ev.get("id")).strip(): ev for ev in events if isinstance(ev, dict)
    }
    payload = [
        {
            "event_id": u["event_id"],
            "event_name": u["event_name"],
            "event_type": u["event_type"],
        }
        for u in uncertain
    ]
    try:
        ai_results = await _call_ai_agent(host, payload)
    except (httpx.HTTPError, ValueError, KeyError):
        return base  # AI unavailable / bad response — keep deterministic result
    if not ai_results:
        return base

    ai_by_id = {_as_str(r.get("event_id")): r for r in ai_results}
    data = _read_all()
    rec = _user_record(data, user_id)
    cache = rec["cache"]
    dirty = False

    for result in base["events"]:
        if result.get("fixed_or_flexible") != "uncertain":
            continue
        ai = ai_by_id.get(result["event_id"])
        if not ai:
            continue
        fx = _as_str(ai.get("fixed_or_flexible")).lower()
        if fx not in _VALID_OVERRIDES:
            continue
        original = by_id.get(result["event_id"])
        # Safety: never let the AI turn a deterministically-fixed event flexible.
        if (
            fx == "flexible"
            and original is not None
            and classify_deterministic(original)["fixed_or_flexible"] == "fixed"
        ):
            fx = "fixed"
        try:
            confidence = float(ai.get("confidence"))
        except (TypeError, ValueError):
            confidence = 0.7
        result["fixed_or_flexible"] = fx
        result["event_type"] = _as_str(ai.get("event_type")) or result["event_type"]
        result["confidence"] = max(0.0, min(confidence, 1.0))
        result["reason"] = _as_str(ai.get("reason")) or "Classified by AI agent."
        result["classified_by"] = "ai"
        if original is not None:
            cache[content_hash(original)] = {
                k: v for k, v in result.items() if k != "classified_by"
            }
            dirty = True

    if dirty:
        data[user_id] = rec
        _write_all(data)

    base["counts"] = {
        "fixed": sum(1 for e in base["events"] if e["fixed_or_flexible"] == "fixed"),
        "flexible": sum(1 for e in base["events"] if e["fixed_or_flexible"] == "flexible"),
        "uncertain": sum(1 for e in base["events"] if e["fixed_or_flexible"] == "uncertain"),
        "cached": base["counts"].get("cached", 0),
        "newly_classified": base["counts"].get("newly_classified", 0),
        "ai_resolved": sum(1 for e in base["events"] if e.get("classified_by") == "ai"),
    }
    return base
