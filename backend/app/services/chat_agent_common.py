# Shared prompts, tool schemas, and tool execution for chat agents (Ollama / OpenAI).
from __future__ import annotations

import re
from typing import Any

from app.services import chat_agent_tools


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

When the user asks what is on their calendar, today's schedule, classes, or events, call get_calendar_events with today's date.
When they ask what is due, today's tasks, homework, or deadlines, call get_tasks and/or get_assignments for the same date range.
If get_calendar_events returns zero events for today, say they have nothing scheduled today — do not mention tomorrow unless asked.
When listing homework, include course_name or display_label (e.g. "CSE 331 — Quiz 4").
For study planning, use estimated_minutes from tasks when proposing blocks via propose_schedule_change.
The app sends calendar busy times and tasks with each message; find_free_slots and propose_schedule_change use them.
Do not invent assignment due dates or calendar events.
Never print debug summaries, raw JSON, or empty lists like "Busy: []" or "Tasks: []" to the user — answer in natural language only.
When you propose schedule changes, remind the user that proposals are not saved until they confirm in the app.
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
# Standalone 24-hour times (not ISO dates like 2026-06-01).
_MILITARY_TIME = re.compile(
    r"\b(?<![:/-])([01]?\d|2[0-3]):([0-5]\d)\b(?!\d)",
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
        if key in ("start_date", "end_date", "deadline", "task_name", "due_start", "due_end"):
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
        return chat_agent_tools.propose_schedule_change(
            params.get("task_name") or "Study block",
            params.get("hours", 1.0),
            params.get("deadline") or "",
            estimated_minutes=params.get("estimated_minutes"),
        )
    return {"error": f"Unknown tool: {tool}"}
