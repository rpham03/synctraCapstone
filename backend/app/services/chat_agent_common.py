# Shared prompts, tool schemas, and tool execution for chat agents (Ollama / OpenAI).
from __future__ import annotations

import re
from typing import Any

from app.services import chat_agent_tools
from app.services import event_classification, productivity_preferences
from app.services.chat_client_context import (
    append_schedule_proposals,
    get_calendar_events,
    get_user_id,
)


def system_instructions() -> str:
    from app.services.chat_client_context import client_timezone_label, effective_today

    today = effective_today()
    mon, fri = chat_agent_tools.week_range_mon_fri(today)
    tz = client_timezone_label()
    return f"""You are Synctra, a friendly AI schedule assistant for university students.
You help users understand their calendar, Canvas assignments, tasks, find open time, and propose study blocks.

TIME FORMAT — critical:
- The user's timezone is {tz} (their phone's local time).
- Always state times in 12-hour form with AM/PM (e.g. 6:45 PM – 7:45 PM).
- Never use 24-hour / military time (do not write 18:45 or 19:45).
- When tools return time_label, when_label, or due_label, quote those exactly.

IMPORTANT — the user's local today is {today.isoformat()} (year {today.year}) on their phone.
For questions about "today", use start_date={today.isoformat()} and end_date={today.isoformat()} in get_calendar_events and get_tasks.
For "this week" (Mon–Fri), use start_date={mon} and end_date={fri} in find_free_slots, get_calendar_events, and get_tasks.
Each calendar event includes local_date (YYYY-MM-DD on the device). Only describe events whose local_date matches the range you queried.
Always use ISO dates YYYY-MM-DD in the current year unless the user names specific past dates.
Use the provided tools when you need real data.

Calendar vs tasks:
- get_calendar_events — classes, meetings, iCal feeds, course imports, manual calendar events, study blocks (what is ON the calendar).
- get_tasks — due items from the Tasks tab (manual + cached Canvas + course import), including estimated_minutes when set.
- get_assignments — live Canvas API sync (due today or later); use for homework when Tasks may be stale.
- add_calendar_block — add a named calendar block only when the user provides title, date, start time, and end time.
- move_calendar_block — move an existing study block to another date, preserving its time unless a new time range is provided.
- delete_calendar_block — delete one or more existing study blocks or manual calendar events the user asks to remove or cancel. Use date filters for duplicate names and only set delete_all_matches when the user explicitly says all/every.

When the user asks what is on their calendar, today's schedule, classes, or events, call get_calendar_events with today's date.
When they ask what is due, today's tasks, homework, or deadlines, call get_tasks and/or get_assignments for the same date range.
If get_calendar_events returns zero events for today, say they have nothing scheduled today — do not mention tomorrow unless asked.
When listing homework, include course_name or display_label (e.g. "CSE 331 — Quiz 4").
For study planning, use estimated_minutes from tasks when proposing blocks via propose_schedule_change.
The app sends calendar busy times and tasks with each message; find_free_slots and propose_schedule_change use them.
For generic requests like "add a block to my calendar", ask for the event name, date, start time, and end time before adding anything.
Do not invent assignment due dates or calendar events.
Never print debug summaries, raw JSON, or empty lists like "Busy: []" or "Tasks: []" to the user — answer in natural language only.
When you propose schedule changes, the app adds those study blocks to the calendar right away.
Be concise and practical."""

TOOL_PARAMETERS: dict[str, dict[str, Any]] = {
    "get_assignments": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    "find_free_slots": {
        "type": "object",
        "properties": {
            "start_date": {"type": "string"},
            "end_date": {"type": "string"},
        },
        "required": ["start_date", "end_date"],
        "additionalProperties": False,
    },
    "get_calendar_events": {
        "type": "object",
        "properties": {
            "start_date": {"type": "string"},
            "end_date": {"type": "string"},
        },
        "required": ["start_date", "end_date"],
        "additionalProperties": False,
    },
    "get_tasks": {
        "type": "object",
        "properties": {
            "due_start": {"type": "string"},
            "due_end": {"type": "string"},
        },
        "required": ["due_start", "due_end"],
        "additionalProperties": False,
    },
    "propose_schedule_change": {
        "type": "object",
        "properties": {
            "task_name": {"type": "string"},
            "hours": {"type": "number"},
            "deadline": {"type": "string"},
            "estimated_minutes": {"type": "integer"},
        },
        "required": ["task_name", "hours", "deadline"],
        "additionalProperties": False,
    },
    "add_calendar_block": {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "start_time": {"type": "string"},
            "end_time": {"type": "string"},
        },
        "required": ["title", "start_time", "end_time"],
        "additionalProperties": False,
    },
    "move_calendar_block": {
        "type": "object",
        "properties": {
            "title_query": {"type": "string"},
            "target_date": {"type": "string"},
            "start_time": {"type": "string"},
            "end_time": {"type": "string"},
        },
        "required": ["title_query", "target_date"],
        "additionalProperties": False,
    },
    "delete_calendar_block": {
        "type": "object",
        "properties": {
            "title_query": {"type": "string"},
            "title_queries": {
                "type": "array",
                "items": {"type": "string"},
            },
            "start_date": {"type": "string"},
            "end_date": {"type": "string"},
            "delete_all_matches": {"type": "boolean"},
        },
        "required": ["title_query"],
        "additionalProperties": False,
    },
    "set_productivity_preferences": {
        "type": "object",
        "properties": {
            "periods": {"type": "array", "items": {"type": "string"}},
            "text": {"type": "string"},
            "start_time": {"type": "string"},
            "end_time": {"type": "string"},
        },
        "additionalProperties": False,
    },
    "get_productivity_preferences": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    "remove_productivity_preferences": {
        "type": "object",
        "properties": {
            "periods": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": False,
    },
    "classify_all_calendar_events": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    "classify_calendar_item": {
        "type": "object",
        "properties": {
            "event_id": {"type": "string"},
            "title": {"type": "string"},
        },
        "additionalProperties": False,
    },
    "set_event_flexibility_override": {
        "type": "object",
        "properties": {
            "event_id": {"type": "string"},
            "title": {"type": "string"},
            "flexibility": {"type": "string"},
        },
        "required": ["flexibility"],
        "additionalProperties": False,
    },
    "suggest_preference_schedule": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    "apply_preference_schedule": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
}

TOOL_DESCRIPTIONS: dict[str, str] = {
    "get_assignments": (
        "Get Canvas assignments due today or later. Each item includes course_name and display_label "
        "(e.g. CSE 331 — Quiz 4) so you can tell classes apart."
    ),
    "find_free_slots": (
        "Find open time blocks between start_date and end_date (ISO YYYY-MM-DD). "
        "Use today's date from the system message for 'this week'."
    ),
    "get_calendar_events": (
        "List calendar events (classes, iCal, course imports, manual events) between "
        "start_date and end_date. Use when the user asks what's on their calendar or schedule."
    ),
    "get_tasks": (
        "List tasks due between due_start and due_end from the Tasks tab (manual + cached Canvas). "
        "Each item may include estimated_minutes for study planning."
    ),
    "propose_schedule_change": (
        "Propose proportional study blocks sized by hours or estimated_minutes, "
        "split into sessions and avoiding calendar busy times. Not saved until confirmed."
    ),
    "add_calendar_block": (
        "Add a named calendar preview block with exact start_time and end_time. "
        "Only use after the user has provided event name, date, start time, and end time."
    ),
    "move_calendar_block": (
        "Move an existing study block to target_date. Preserve its current time and "
        "duration unless start_time and end_time are provided."
    ),
    "delete_calendar_block": (
        "Delete one or more existing study blocks or manual calendar events. "
        "Use title_queries for multiple named events, optional dates to narrow "
        "duplicates, and delete_all_matches only when the user explicitly says all."
    ),
    "set_productivity_preferences": (
        "Save the user's productive periods (morning/afternoon/evening/night), "
        "optionally with explicit start/end times. Then ask if they want a schedule."
    ),
    "get_productivity_preferences": "Return the user's saved productive periods.",
    "remove_productivity_preferences": (
        "Remove specific productive periods, or all when none are given."
    ),
    "classify_all_calendar_events": (
        "Classify every calendar event as fixed or flexible (with type and "
        "confidence), using safety rules and cached results."
    ),
    "classify_calendar_item": (
        "Classify a single calendar event (by event_id or title) as fixed/flexible."
    ),
    "set_event_flexibility_override": (
        "Persist the user's explicit fixed/flexible choice for an event; this "
        "override always wins over rules and AI."
    ),
    "suggest_preference_schedule": (
        "Preview blocks that place flexible work near the user's preferred "
        "periods without moving fixed events. Preview only — not applied."
    ),
    "apply_preference_schedule": (
        "Apply the preference-based schedule after the user confirms."
    ),
}

MAX_TOOL_ROUNDS = 8

# LLMs sometimes echo empty tool/context dumps — strip before showing in the app.
_DEBUG_LINE = re.compile(
    r"^\s*(Busy|Tasks|Assignments):\s*(\[\])?\s*,?\s*$",
    re.IGNORECASE,
)
_DEBUG_ONLY = re.compile(
    r"^\s*Busy:\s*\[\]\s*,?\s*Tasks:\s*\[\]\s*,?\s*Assignments:\s*\[\]\s*$",
    re.IGNORECASE | re.DOTALL,
)
# Standalone 24-hour times (not ISO dates like 2026-06-01, and not already 12-hour with AM/PM).
_MILITARY_TIME = re.compile(
    r"\b(?<![:/-])([01]?\d|2[0-3]):([0-5]\d)\b(?!\d)(?!\s*[AaPp][Mm]\b)",
)


def _military_to_12h(hour: int, minute: int) -> str:
    h12 = hour % 12 or 12
    suffix = "AM" if hour < 12 else "PM"
    return f"{h12}:{minute:02d} {suffix}"


def normalize_reply_times(text: str) -> str:
    """Convert accidental 24-hour times in replies to 12-hour AM/PM."""

    def repl(match: re.Match[str]) -> str:
        hour = int(match.group(1))
        minute = int(match.group(2))
        return _military_to_12h(hour, minute)

    return _MILITARY_TIME.sub(repl, text)


def sanitize_chat_reply(text: str) -> str:
    """Remove debug-style context dumps from model replies."""
    if not text or not text.strip():
        return text
    if _DEBUG_ONLY.match(text.strip()):
        return (
            "I don't see anything on your calendar or task list for that range yet. "
            "Sync iCal or course imports in Calendar, and Canvas or manual tasks in Tasks, then ask again."
        )
    lines = [ln for ln in text.splitlines() if not _DEBUG_LINE.match(ln.strip())]
    cleaned = "\n".join(lines).strip()
    cleaned = normalize_reply_times(cleaned)
    return cleaned if cleaned else normalize_reply_times(text)


def coerce_text(value: Any, *, default: str = "") -> str:
    """Normalize Ollama/OpenAI fields that may be str, dict, or list."""
    if value is None:
        return default
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, dict):
        for key in ("content", "text", "value", "date", "name"):
            if key in value:
                return coerce_text(value[key], default=default)
        return default
    if isinstance(value, list):
        parts = [coerce_text(v, default="") for v in value]
        joined = "\n".join(p for p in parts if p)
        return joined or default
    return default


def coerce_tool_name(value: Any) -> str:
    name = coerce_text(value, default="")
    return name.strip()


def normalize_tool_args(args: dict[str, Any]) -> dict[str, Any]:
    """Coerce tool argument values to types our handlers expect."""
    out: dict[str, Any] = {}
    for key, val in args.items():
        if key in (
            "start_date",
            "end_date",
            "deadline",
            "task_name",
            "due_start",
            "due_end",
            "title",
            "start_time",
            "end_time",
            "title_query",
            "target_date",
        ):
            out[key] = coerce_text(val, default="")
        elif key == "hours":
            if isinstance(val, (int, float)):
                out[key] = float(val)
            elif isinstance(val, str):
                try:
                    out[key] = float(val.strip())
                except ValueError:
                    out[key] = 1.0
            else:
                out[key] = 1.0
        elif key == "estimated_minutes":
            if isinstance(val, (int, float)):
                out[key] = int(val)
            elif isinstance(val, str):
                try:
                    out[key] = int(float(val.strip()))
                except ValueError:
                    out[key] = None
            else:
                out[key] = None
        elif key in {"title_queries", "delete_block_ids"}:
            out[key] = [
                coerce_text(item, default="").strip()
                for item in val
                if coerce_text(item, default="").strip()
            ] if isinstance(val, list) else []
        elif key == "delete_all_matches":
            out[key] = (
                val.strip().lower() in {"1", "true", "yes", "all"}
                if isinstance(val, str)
                else bool(val)
            )
        else:
            out[key] = val
    return out


def openai_tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "name": name,
            "description": TOOL_DESCRIPTIONS[name],
            "parameters": TOOL_PARAMETERS[name],
            "strict": True,
        }
        for name in TOOL_DESCRIPTIONS
    ]


def ollama_tools() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": TOOL_DESCRIPTIONS[name],
                "parameters": TOOL_PARAMETERS[name],
            },
        }
        for name in TOOL_DESCRIPTIONS
    ]


async def execute_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    tool = coerce_tool_name(name)
    params = normalize_tool_args(args if isinstance(args, dict) else {})
    if tool == "get_assignments":
        return await chat_agent_tools.get_assignments_from_canvas()
    if tool == "find_free_slots":
        start = params.get("start_date") or ""
        end = params.get("end_date") or ""
        if not start or not end:
            return {
                "error": "start_date and end_date are required (ISO date strings).",
                "slots": [],
            }
        return chat_agent_tools.find_free_slots_in_calendar(start, end)
    if tool == "get_calendar_events":
        start = params.get("start_date") or ""
        end = params.get("end_date") or ""
        if not start or not end:
            return {
                "error": "start_date and end_date are required (ISO date strings).",
                "events": [],
            }
        return chat_agent_tools.list_calendar_events_for_range(start, end)
    if tool == "get_tasks":
        start = params.get("due_start") or ""
        end = params.get("due_end") or ""
        if not start or not end:
            return {
                "error": "due_start and due_end are required (ISO date strings).",
                "tasks": [],
            }
        return chat_agent_tools.list_tasks_for_range(start, end)
    if tool == "propose_schedule_change":
        result = chat_agent_tools.propose_schedule_change(
            params.get("task_name") or "Study block",
            params.get("hours", 1.0),
            params.get("deadline") or "",
            estimated_minutes=params.get("estimated_minutes"),
        )
        proposal = result.get("proposal")
        if isinstance(proposal, list):
            append_schedule_proposals(proposal)
        return result
    if tool == "add_calendar_block":
        title = (params.get("title") or "").strip()
        start_time = (params.get("start_time") or "").strip()
        end_time = (params.get("end_time") or "").strip()
        if not title or not start_time or not end_time:
            return {
                "error": "title, start_time, and end_time are required.",
                "proposal": [],
            }
        proposal = [
            {
                "task_title": title,
                "start_time": start_time,
                "end_time": end_time,
                "duration_minutes": None,
                "is_ai_generated": False,
                "written_to_calendar": False,
            }
        ]
        append_schedule_proposals(proposal)
        return {
            "proposal": proposal,
            "message": "I added this calendar block to your calendar preview.",
        }
    if tool == "move_calendar_block":
        result = chat_agent_tools.move_calendar_block(
            params.get("title_query") or "study block",
            params.get("target_date") or "",
            start_time=params.get("start_time") or "",
            end_time=params.get("end_time") or "",
        )
        proposal = result.get("proposal")
        if isinstance(proposal, list):
            append_schedule_proposals(proposal)
        return result
    if tool == "delete_calendar_block":
        result = chat_agent_tools.delete_calendar_block(
            params.get("title_query") or "event",
            title_queries=params.get("title_queries"),
            delete_block_ids=params.get("delete_block_ids"),
            start_date=params.get("start_date") or "",
            end_date=params.get("end_date") or "",
            delete_all_matches=params.get("delete_all_matches", False),
        )
        proposal = result.get("proposal")
        if isinstance(proposal, list):
            append_schedule_proposals(proposal)
        return result
    if tool == "set_productivity_preferences":
        periods = _periods_arg(params)
        if not periods:
            return {
                "error": "Which time of day are you most productive — morning, "
                "afternoon, evening, or night?",
                "preferences": productivity_preferences.get_preferences(get_user_id()),
            }
        prefs = productivity_preferences.set_preferences(
            get_user_id(),
            periods,
            start=params.get("start_time") or "",
            end=params.get("end_time") or "",
        )
        return {"preferences": prefs, "saved": periods}
    if tool == "get_productivity_preferences":
        return {"preferences": productivity_preferences.get_preferences(get_user_id())}
    if tool == "remove_productivity_preferences":
        remaining = productivity_preferences.remove_preferences(
            get_user_id(), _periods_arg(params) or None
        )
        return {"preferences": remaining}
    if tool == "classify_all_calendar_events":
        return await event_classification.classify_all_calendar_events_with_ai(
            get_calendar_events(), user_id=get_user_id()
        )
    if tool == "classify_calendar_item":
        event = _resolve_event(params.get("event_id"), params.get("title"))
        if event is None:
            return {"error": "I couldn't find that event to classify."}
        user_id = get_user_id()
        override = event_classification.get_override(
            user_id, str(event.get("id") or "")
        )
        result = event_classification.classify_deterministic(event)
        if override:
            result = {**result, "fixed_or_flexible": override, "classified_by": "override"}
        return {"event": result}
    if tool == "set_event_flexibility_override":
        event = _resolve_event(params.get("event_id"), params.get("title"))
        event_id = str((event or {}).get("id") or params.get("event_id") or "").strip()
        flexibility = str(params.get("flexibility") or "").strip().lower()
        if not event_id or flexibility not in {"fixed", "flexible"}:
            return {"error": "Tell me the event and whether it is fixed or flexible."}
        event_classification.set_override(get_user_id(), event_id, flexibility)
        return {
            "event_id": event_id,
            "flexibility": flexibility,
            "title": str((event or {}).get("title") or ""),
        }
    if tool == "suggest_preference_schedule":
        from app.services import preference_scheduler

        return preference_scheduler.suggest_preference_schedule(user_id=get_user_id())
    if tool == "apply_preference_schedule":
        from app.services import preference_scheduler

        result = preference_scheduler.suggest_preference_schedule(user_id=get_user_id())
        proposal = result.get("proposals")
        if isinstance(proposal, list):
            append_schedule_proposals(proposal)
        return result
    return {"error": f"Unknown tool: {tool}"}


def _periods_arg(params: dict[str, Any]) -> list[str]:
    """Normalize a periods list and/or free text into canonical periods."""

    raw = params.get("periods")
    periods: list[str] = []
    if isinstance(raw, list):
        periods = [
            str(p).strip().lower()
            for p in raw
            if str(p).strip().lower() in productivity_preferences.DEFAULT_RANGES
        ]
    if not periods:
        periods = productivity_preferences.detect_periods(str(params.get("text") or ""))
    # De-dup, preserve order.
    seen: set[str] = set()
    return [p for p in periods if not (p in seen or seen.add(p))]


def _resolve_event(event_id: object, title: object) -> dict[str, Any] | None:
    """Find a calendar event by id, else by case-insensitive title match."""

    events = get_calendar_events()
    wanted_id = str(event_id or "").strip()
    if wanted_id:
        for event in events:
            if str(event.get("id") or "").strip() == wanted_id:
                return event
    query = str(title or "").strip().lower()
    if query:
        for event in events:
            name = str(event.get("title") or "").strip().lower()
            if name and (query == name or query in name or name in query):
                return event
    return None
