# Shared prompts, tool schemas, and tool execution for chat agents (Ollama / OpenAI).
from __future__ import annotations

from typing import Any

from app.services import chat_agent_tools


def system_instructions() -> str:
    today = chat_agent_tools.today_local()
    mon, fri = chat_agent_tools.week_range_mon_fri(today)
    return f"""You are Synctra, a friendly AI schedule assistant for university students.
You help users understand Canvas assignments, find open time on their calendar, and propose study blocks.

IMPORTANT — today's date is {today.isoformat()} (year {today.year}).
For "this week" (Mon–Fri), use start_date={mon} and end_date={fri} in find_free_slots.
Always use ISO dates YYYY-MM-DD in the current year unless the user names specific past dates.
Use the provided tools when you need real data. get_assignments only includes work due today or later.
When listing homework, always include each item's course_name (or display_label), e.g. "CSE 331 — Quiz 4", not just the assignment title.
The app sends calendar/iCal busy times with each message;
find_free_slots subtracts those from the day. Do not invent assignment due dates or calendar events.
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
    "propose_schedule_change": {
        "type": "object",
        "properties": {
            "task_name": {"type": "string"},
            "hours": {"type": "number"},
            "deadline": {"type": "string"},
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
    "propose_schedule_change": "Propose study blocks without writing to the calendar yet.",
}

MAX_TOOL_ROUNDS = 8


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
        if key in ("start_date", "end_date", "deadline", "task_name"):
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
    if tool == "propose_schedule_change":
        return chat_agent_tools.propose_schedule_change(
            params.get("task_name") or "Study block",
            params.get("hours", 1.0),
            params.get("deadline") or "",
        )
    return {"error": f"Unknown tool: {tool}"}
