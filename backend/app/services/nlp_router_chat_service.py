"""Chat service backed by the trained NLP tool router."""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any

import httpx

from app.core.config.settings import settings
from app.services.chat_agent_common import execute_tool, sanitize_chat_reply
from app.services.chat_client_context import effective_today


CLARIFICATION_ACTION = "clarification"
LOCAL_TOOL_NAMES = {
    "get_tasks",
    "get_calendar_events",
    "propose_schedule_change",
    "add_calendar_block",
}
TUNNEL_REQUEST_HEADERS = {
    "Accept": "application/json",
    "ngrok-skip-browser-warning": "true",
}
_pending_nlu_context: dict[str, dict[str, Any]] = {}


class NlpRouterChatService:
    """Plan with the trained NLP router, then execute Synctra tools locally."""

    def _router_host(self) -> str:
        host = (
            os.getenv("COLAB_NLP_ROUTER_HOST")
            or os.getenv("COLAB_ROUTER_HOST")
            or settings.colab_nlp_router_host
            or ""
        ).strip()
        if not host:
            raise RuntimeError(
                "Colab NLP router is not configured. Set COLAB_NLP_ROUTER_HOST "
                "to the tunnel URL printed by tool/colab_nlp_router_agent_server.py."
            )
        return host.rstrip("/")

    def _ai_agent_host(self) -> str:
        # The Colab all-in-one stack serves /plan AND /api/generate on the
        # same port, so the NLP router host is always a valid fallback.
        host = (
            os.getenv("COLAB_AI_AGENT_HOST")
            or settings.colab_ai_agent_host
            or os.getenv("COLAB_COURSE_IMPORT_HOST")
            or settings.colab_course_import_host
            or os.getenv("OLLAMA_HOST")
            or self._configured_ollama_host()
            or os.getenv("COLAB_NLP_ROUTER_HOST")
            or settings.colab_nlp_router_host
            or ""
        ).strip()
        if not host:
            raise RuntimeError(
                "Colab ai_agent is not configured. Set COLAB_AI_AGENT_HOST or "
                "COLAB_COURSE_IMPORT_HOST to an /api/generate server."
            )
        return host.rstrip("/")

    def _configured_ollama_host(self) -> str:
        host = (settings.ollama_host or "").strip().rstrip("/")
        if host in {"http://localhost:11434", "http://127.0.0.1:11434"}:
            return ""
        return host

    def _ai_agent_model(self) -> str:
        return (
            os.getenv("COLAB_AI_AGENT_MODEL")
            or settings.colab_ai_agent_model
            or os.getenv("COLAB_COURSE_IMPORT_MODEL")
            or settings.colab_course_import_model
            or "Qwen/Qwen2.5-3B-Instruct"
        ).strip()

    async def run_turn(self, user_message: str, *, user_id: str | None = None) -> str:
        pending = _pending_nlu_context.get(user_id) if user_id else None
        if pending and user_message.strip().lower() in {
            "cancel",
            "cancel it",
            "never mind",
            "nevermind",
            "stop",
        }:
            if user_id:
                _pending_nlu_context.pop(user_id, None)
            return "Okay, I canceled that request."

        planning_message = user_message
        if pending:
            original = str(pending.get("message") or "").strip()
            planning_message = f"{original} {user_message}".strip()

        async with httpx.AsyncClient(timeout=60.0) as client:
            planned = await self._fetch_plan(
                client,
                planning_message,
                clarification_pending=bool(pending),
            )
            if not planned:
                if user_id:
                    _pending_nlu_context.pop(user_id, None)
                return await self._ai_agent_reply(client, user_message)

            parts: list[str] = []

            for raw_call in planned:
                name = str(raw_call.get("name") or "ai_agent")
                args = raw_call.get("arguments") if isinstance(raw_call, dict) else {}
                arguments = args if isinstance(args, dict) else {}

                if name == CLARIFICATION_ACTION:
                    question = str(arguments.get("question") or "").strip()
                    if user_id:
                        _pending_nlu_context[user_id] = {
                            "message": planning_message,
                            "slots": dict(arguments.get("slots") or {}),
                            "missing_slots": list(arguments.get("missing_slots") or []),
                            "predicted_tool": str(arguments.get("predicted_tool") or ""),
                        }
                    return question or "Can you clarify what you want me to do?"

                if name == "ai_agent":
                    if user_id:
                        _pending_nlu_context.pop(user_id, None)
                    message = str(arguments.get("message") or user_message)
                    return await self._ai_agent_reply(client, message)

                if name not in LOCAL_TOOL_NAMES:
                    if user_id:
                        _pending_nlu_context.pop(user_id, None)
                    message = str(arguments.get("message") or user_message)
                    return await self._ai_agent_reply(client, message)

                verification_question = self._verify_local_tool_call(
                    name,
                    arguments,
                    planning_message,
                )
                if verification_question:
                    if user_id:
                        _pending_nlu_context[user_id] = {
                            "message": planning_message,
                            "slots": {},
                            "missing_slots": [],
                            "predicted_tool": name,
                        }
                    return verification_question

                if user_id:
                    _pending_nlu_context.pop(user_id, None)
                result = await execute_tool(name, arguments)
                parts.append(self._format_tool_result(name, result))

            reply = "\n\n".join(part for part in parts if part).strip()
            return sanitize_chat_reply(reply) or await self._ai_agent_reply(
                client, user_message
            )

    async def _ai_agent_reply(self, client: httpx.AsyncClient, message: str) -> str:
        ai_result = await self._call_ai_agent(client, message)
        if ai_result.get("error"):
            return sanitize_chat_reply(str(ai_result["error"]))
        assistant = str(ai_result.get("assistant_message") or "").strip()
        return sanitize_chat_reply(assistant) or "I could not generate a reply."

    def _verify_local_tool_call(
        self,
        name: str,
        arguments: dict[str, Any],
        user_message: str,
    ) -> str | None:
        """Second-pass guard before executing local tools.

        Verification 1: make sure the chosen tool matches the user's wording.
        Verification 2: make sure all required arguments are specific enough.
        """

        lower = user_message.lower()
        if name == "add_calendar_block":
            if not (
                self._looks_like_calendar_block_request(lower)
                or self._looks_like_calendar_block_details(lower)
            ):
                return (
                    "Do you want me to add a calendar block? If so, send the "
                    "event name, date, start time, and end time."
                )
            return self._verify_add_calendar_block(arguments)
        if name == "propose_schedule_change":
            if self._looks_like_calendar_block_details(lower):
                return (
                    "I see an event name, date, and time range. Should I add this "
                    "as a calendar block? Send it like: Study for CSE 369 on "
                    "Thursday from 7 PM to 9 PM."
                )
            task_name = str(arguments.get("task_name") or "").strip().lower()
            if task_name in {
                "",
                "study block",
                "this week",
                "today",
                "tomorrow",
                "weekend",
                "this weekend",
                "plan",
            }:
                return (
                    "Before I add anything, what event name, date, start time, "
                    "and end time should I use?"
                )
            missing: list[str] = []
            if not self._has_duration(lower):
                missing.append("duration")
            if not self._has_deadline_text(lower):
                missing.append("deadline")
            if missing:
                return (
                    f"What {' and '.join(missing)} should I use for this study "
                    "schedule? For example: Schedule 2 hours for lab 7 by Friday."
                )
            if not (
                self._has_any(lower, ("schedule", "study", "homework", "assignment"))
                or self._has_duration(lower)
            ):
                return (
                    "Do you want me to schedule study time, or add a calendar block? "
                    "For a calendar block, send event name, date, start time, and end time."
                )
            return None
        if name == "get_tasks":
            if not self._has_any(
                lower,
                ("due", "deadline", "homework", "assignment", "task", "submit"),
            ):
                return (
                    "Do you want me to check tasks and due dates, or something else?"
                )
            return self._require_args(arguments, ("due_start", "due_end"), "due date range")
        if name == "get_calendar_events":
            if self._looks_like_calendar_block_request(lower):
                return (
                    "What event name should I use for this calendar block?"
                )
            if not self._has_any(
                lower,
                ("calendar", "schedule", "class", "meeting", "event", "lecture", "lab"),
            ):
                return (
                    "Do you want me to show calendar events, or add something to the calendar?"
                )
            return self._require_args(
                arguments,
                ("start_date", "end_date"),
                "calendar date range",
            )
        return None

    def _verify_add_calendar_block(self, arguments: dict[str, Any]) -> str | None:
        title = str(arguments.get("title") or "").strip()
        start_raw = str(arguments.get("start_time") or "").strip()
        end_raw = str(arguments.get("end_time") or "").strip()
        generic_titles = {"", "calendar", "block", "calendar block", "event", "study block"}
        if title.lower() in generic_titles:
            return "What event name should I use for this calendar block?"
        if not start_raw or not end_raw:
            return "What start time and end time should I use for this calendar block?"
        try:
            start = datetime.fromisoformat(start_raw.replace("Z", "+00:00"))
            end = datetime.fromisoformat(end_raw.replace("Z", "+00:00"))
        except ValueError:
            return (
                "I could not read that date or time. Please send the event name, "
                "date, start time, and end time."
            )
        if end <= start:
            return "The end time must be after the start time. What time should it end?"
        return None

    def _require_args(
        self,
        arguments: dict[str, Any],
        keys: tuple[str, ...],
        label: str,
    ) -> str | None:
        if all(str(arguments.get(key) or "").strip() for key in keys):
            return None
        return f"What {label} should I use?"

    def _looks_like_calendar_block_details(self, text: str) -> bool:
        has_time_range = bool(
            re.search(
                r"\b\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?\s*"
                r"(?:-|to|until|through)\s*"
                r"\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)\b",
                text,
                flags=re.IGNORECASE,
            )
        )
        has_date = self._has_any(
            text,
            (
                "today",
                "tomorrow",
                "monday",
                "tuesday",
                "wednesday",
                "thursday",
                "friday",
                "saturday",
                "sunday",
            ),
        ) or bool(re.search(r"\b\d{1,2}(?:st|nd|rd|th)\b", text))
        return has_time_range and has_date

    def _looks_like_calendar_block_request(self, text: str) -> bool:
        return any(
            phrase in text
            for phrase in (
                "add a block to my calendar",
                "add a block in my calendar",
                "add a block on my calendar",
                "add a block to calendar",
                "add a block in calendar",
                "add block to my calendar",
                "add block to calendar",
                "add a calendar block",
                "add calendar block",
                "create a calendar block",
                "put a block on my calendar",
                "put a block in my calendar",
                "add a study block to my calendar",
                "add a study block in my calendar",
                "add study block to my calendar",
                "add study time to my calendar",
                "add study time in my calendar",
            )
        )

    def _has_duration(self, text: str) -> bool:
        return bool(
            re.search(
                r"\b\d+(?:\.\d+)?\s*(?:h|hr|hrs|hour|hours|m|min|mins|minute|minutes)\b",
                text,
            )
        )

    def _has_deadline_text(self, text: str) -> bool:
        return bool(
            re.search(
                r"\b(?:today|tomorrow|this week|next week|monday|tuesday|"
                r"wednesday|thursday|friday|saturday|sunday|20\d{2}-\d{2}-\d{2})\b",
                text,
            )
        )

    def _has_any(self, text: str, terms: tuple[str, ...]) -> bool:
        return any(term in text for term in terms)

    async def _fetch_plan(
        self,
        client: httpx.AsyncClient,
        message: str,
        *,
        clarification_pending: bool = False,
    ) -> list[dict[str, Any]]:
        payload = {
            "message": message,
            "clarification_pending": clarification_pending,
            "today": effective_today().isoformat(),
        }
        try:
            response = await client.post(
                f"{self._router_host()}/plan",
                json=payload,
                headers=TUNNEL_REQUEST_HEADERS,
            )
            response.raise_for_status()
        except httpx.RequestError as exc:
            raise RuntimeError(
                "Could not reach the Colab NLP router. Start "
                "tool/colab_nlp_router_agent_server.py and set COLAB_NLP_ROUTER_HOST."
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:400] if exc.response is not None else str(exc)
            raise RuntimeError(f"Colab NLP router error: {detail}") from exc

        try:
            body = response.json()
        except ValueError as exc:
            detail = response.text[:400]
            if "ngrok" in detail.lower() or "<!doctype html" in detail.lower():
                raise RuntimeError(
                    "Colab NLP router returned an HTML tunnel page instead of JSON. "
                    "If you are using ngrok, restart the backend with the latest code "
                    "so requests include ngrok-skip-browser-warning, or use a "
                    "cloudflared tunnel for the NLP router."
                ) from exc
            raise RuntimeError(f"Colab NLP router returned non-JSON response: {detail}") from exc
        calls = body.get("tool_calls") or body.get("plan") or []
        if not isinstance(calls, list):
            raise RuntimeError(f"Colab NLP router returned an unexpected payload: {body!r}")
        return [call for call in calls if isinstance(call, dict)]

    async def _call_ai_agent(
        self,
        client: httpx.AsyncClient,
        message: str,
    ) -> dict[str, Any]:
        try:
            host = self._ai_agent_host()
        except RuntimeError as exc:
            return {"error": str(exc), "message": message}

        url = f"{host}/api/generate"
        payload = {
            "model": self._ai_agent_model(),
            "prompt": message,
            "stream": False,
            "options": {"temperature": 0.2, "syntra_mode": "ai_agent"},
        }
        print(f"[ai_agent] POST {url} prompt={message[:80]!r}", flush=True)
        try:
            response = await client.post(
                url,
                json=payload,
                headers=TUNNEL_REQUEST_HEADERS,
                timeout=120.0,
            )
            response.raise_for_status()
        except httpx.RequestError as exc:
            print(f"[ai_agent] request error: {exc}", flush=True)
            return {"error": f"Colab ai_agent request failed: {exc}", "message": message}
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text[:400] if exc.response is not None else str(exc)
            print(f"[ai_agent] http error {exc.response.status_code}: {detail}", flush=True)
            return {"error": f"Colab ai_agent error: {detail}", "message": message}

        try:
            data = response.json()
        except ValueError as exc:
            preview = response.text[:200]
            print(f"[ai_agent] non-JSON response: {preview!r}", flush=True)
            return {"error": f"Colab ai_agent returned non-JSON: {preview}", "message": message}
        return {
            "assistant_message": str(data.get("response") or "").strip(),
            "raw": data,
        }

    def _format_tool_result(self, name: str, result: dict[str, Any]) -> str:
        if result.get("error"):
            return str(result["error"])
        if name == "get_tasks":
            return self._format_tasks(result)
        if name == "get_calendar_events":
            return self._format_events(result)
        if name == "find_free_slots":
            return self._format_slots(result)
        if name == "get_assignments":
            return self._format_assignments(result)
        if name == "propose_schedule_change":
            return self._format_proposal(result)
        if name == "add_calendar_block":
            return self._format_calendar_block(result)
        return str(result)

    def _format_tasks(self, result: dict[str, Any]) -> str:
        tasks = result.get("tasks") if isinstance(result.get("tasks"), list) else []
        if not tasks:
            return str(result.get("note") or "No tasks found for that range.")
        lines = ["Here is what is due:"]
        for task in tasks[:8]:
            if not isinstance(task, dict):
                continue
            title = task.get("display_label") or task.get("title") or "Task"
            due = self._short_time(task.get("due_date"))
            lines.append(f"- {title}" + (f" due {due}" if due else ""))
        if len(tasks) > 8:
            lines.append(f"- plus {len(tasks) - 8} more")
        return "\n".join(lines)

    def _format_events(self, result: dict[str, Any]) -> str:
        events = result.get("events") if isinstance(result.get("events"), list) else []
        if not events:
            return str(result.get("note") or "No calendar events found for that range.")
        lines = ["Here is what is on your calendar:"]
        for event in events[:8]:
            if not isinstance(event, dict):
                continue
            title = event.get("title") or "Event"
            start = self._short_time(event.get("start_time"))
            end = self._short_time(event.get("end_time"))
            when = f" from {start} to {end}" if start and end else ""
            lines.append(f"- {title}{when}")
        if len(events) > 8:
            lines.append(f"- plus {len(events) - 8} more")
        return "\n".join(lines)

    def _format_slots(self, result: dict[str, Any]) -> str:
        slots = result.get("slots") if isinstance(result.get("slots"), list) else []
        if not slots:
            return str(result.get("note") or "No free slots found for that range.")
        lines = ["I found these open blocks:"]
        for slot in slots[:8]:
            if not isinstance(slot, dict):
                continue
            start = self._short_time(slot.get("start"))
            end = self._short_time(slot.get("end"))
            minutes = slot.get("minutes_available")
            suffix = f" ({minutes} min)" if minutes else ""
            lines.append(f"- {start} to {end}{suffix}")
        if len(slots) > 8:
            lines.append(f"- plus {len(slots) - 8} more")
        return "\n".join(lines)

    def _format_assignments(self, result: dict[str, Any]) -> str:
        assignments = (
            result.get("assignments") if isinstance(result.get("assignments"), list) else []
        )
        if not assignments:
            return str(result.get("error") or "No Canvas assignments found.")
        lines = ["Canvas assignments:"]
        for item in assignments[:8]:
            if not isinstance(item, dict):
                continue
            title = item.get("display_label") or item.get("title") or "Assignment"
            due = self._short_time(item.get("due_date"))
            lines.append(f"- {title}" + (f" due {due}" if due else ""))
        if len(assignments) > 8:
            lines.append(f"- plus {len(assignments) - 8} more")
        return "\n".join(lines)

    def _format_proposal(self, result: dict[str, Any]) -> str:
        message = str(result.get("message") or "").strip()
        proposal = result.get("proposal") if isinstance(result.get("proposal"), list) else []
        if not proposal:
            return message or "I could not find a schedule proposal."
        if "not saved to your calendar yet" in message.lower():
            message = message.replace(
                "Proposal only — not saved to your calendar yet.",
                "I added this study block to your calendar preview.",
            )
        lines = [message or "I added this study block to your calendar preview."]
        for block in proposal[:8]:
            if not isinstance(block, dict):
                continue
            title = block.get("task_title") or "Study block"
            start = self._short_time(block.get("start_time"))
            end = self._short_time(block.get("end_time"))
            lines.append(f"- {title}: {start} to {end}")
        return "\n".join(lines)

    def _format_calendar_block(self, result: dict[str, Any]) -> str:
        message = str(result.get("message") or "").strip()
        proposal = result.get("proposal") if isinstance(result.get("proposal"), list) else []
        if not proposal:
            return message or "I could not add that calendar block."
        lines = [message or "I added this calendar block to your calendar preview."]
        for block in proposal[:8]:
            if not isinstance(block, dict):
                continue
            title = block.get("task_title") or "Calendar block"
            start = self._short_time(block.get("start_time"))
            end = self._short_time(block.get("end_time"))
            lines.append(f"- {title}: {start} to {end}")
        return "\n".join(lines)

    def _short_time(self, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            return ""
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return text
        if parsed.minute:
            return parsed.strftime("%b %-d, %-I:%M %p")
        return parsed.strftime("%b %-d, %-I %p")
