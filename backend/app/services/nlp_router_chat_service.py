"""Chat service backed by the trained NLP tool router."""

from __future__ import annotations

import os
import re
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from app.core.config.settings import settings
from app.services import chat_agent_tools
from app.services.chat_agent_common import execute_tool, sanitize_chat_reply
from app.services.chat_client_context import effective_today


CLARIFICATION_ACTION = "clarification"
LOCAL_TOOL_NAMES = {
    "get_tasks",
    "get_calendar_events",
    "propose_schedule_change",
    "add_calendar_block",
    "move_calendar_block",
    "delete_calendar_block",
}
TUNNEL_REQUEST_HEADERS = {
    "Accept": "application/json",
    "ngrok-skip-browser-warning": "true",
}
_pending_nlu_context: dict[str, dict[str, Any]] = {}
_AFFIRMATIVE_REPLIES = {
    "yes",
    "yes please",
    "sure",
    "okay",
    "ok",
    "confirm",
    "do it",
    "please do",
}
_CANCEL_REPLIES = {
    "cancel",
    "cancel it",
    "never mind",
    "nevermind",
    "stop",
    "no",
    "no thanks",
}


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

    async def run_turn(
        self,
        user_message: str,
        *,
        user_id: str | None = None,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        pending = _pending_nlu_context.get(user_id) if user_id else None
        normalized_reply = self._normalized_reply(user_message)
        if pending and normalized_reply in _CANCEL_REPLIES:
            if user_id:
                _pending_nlu_context.pop(user_id, None)
            return "Okay, I canceled that request."

        if pending and normalized_reply in _AFFIRMATIVE_REPLIES:
            pending_call = pending.get("pending_call")
            if isinstance(pending_call, dict):
                name = str(pending_call.get("name") or "")
                args = pending_call.get("arguments")
                arguments = args if isinstance(args, dict) else {}
                if name in LOCAL_TOOL_NAMES:
                    if user_id:
                        _pending_nlu_context.pop(user_id, None)
                    result = await execute_tool(name, arguments)
                    return sanitize_chat_reply(self._format_tool_result(name, result))

        if pending and self._starts_new_request(user_message, pending):
            if user_id:
                _pending_nlu_context.pop(user_id, None)
            pending = None

        planning_message = user_message
        if pending:
            original = str(pending.get("message") or "").strip()
            planning_message = (
                original
                if normalized_reply in _AFFIRMATIVE_REPLIES
                else self._merge_pending_reply(original, user_message, pending)
            )

        async with httpx.AsyncClient(timeout=60.0) as client:
            async def ai_reply(message: str) -> str:
                if history:
                    return await self._ai_agent_reply(client, message, history=history)
                return await self._ai_agent_reply(client, message)

            planned = await self._fetch_plan(
                client,
                planning_message,
                clarification_pending=bool(pending),
            )
            if not planned:
                if user_id:
                    _pending_nlu_context.pop(user_id, None)
                return await ai_reply(user_message)

            parts: list[str] = []

            for raw_call in planned:
                name = str(raw_call.get("name") or "ai_agent")
                args = raw_call.get("arguments") if isinstance(raw_call, dict) else {}
                arguments = args if isinstance(args, dict) else {}

                name, arguments = self._coerce_move_intent(
                    name, arguments, planning_message
                )
                name, arguments = self._coerce_delete_intent(
                    name, arguments, planning_message
                )

                if name == CLARIFICATION_ACTION:
                    question = str(arguments.get("question") or "").strip()
                    new_missing = list(arguments.get("missing_slots") or [])
                    # Loop guard: the user just answered a clarification and the
                    # router wants to ask the exact same thing again. Re-asking
                    # spins forever (e.g. asking AM/PM when no time was given),
                    # so break out instead of repeating the prompt.
                    if pending and self._is_repeat_clarification(
                        pending, question, new_missing
                    ):
                        if user_id:
                            _pending_nlu_context.pop(user_id, None)
                        return self._loop_break_message(pending)
                    if user_id:
                        _pending_nlu_context[user_id] = {
                            "message": planning_message,
                            "slots": dict(arguments.get("slots") or {}),
                            "missing_slots": new_missing,
                            "predicted_tool": str(arguments.get("predicted_tool") or ""),
                            "question": question,
                        }
                    return question or "Can you clarify what you want me to do?"

                if name == "ai_agent":
                    if user_id:
                        _pending_nlu_context.pop(user_id, None)
                    message = str(arguments.get("message") or user_message)
                    return await ai_reply(message)

                if name not in LOCAL_TOOL_NAMES:
                    if user_id:
                        _pending_nlu_context.pop(user_id, None)
                    message = str(arguments.get("message") or user_message)
                    return await ai_reply(message)

                verification_question = self._verify_local_tool_call(
                    name,
                    arguments,
                    planning_message,
                )
                if verification_question:
                    # Loop guard: the user just answered this exact verification
                    # question and we're about to ask it again — break out.
                    if pending and self._normalized_reply(
                        str(pending.get("question") or "")
                    ) == self._normalized_reply(verification_question):
                        if user_id:
                            _pending_nlu_context.pop(user_id, None)
                        return self._loop_break_message(pending)
                    if user_id:
                        pending_state: dict[str, Any] = {
                            "message": planning_message,
                            "slots": {},
                            "missing_slots": [],
                            "predicted_tool": name,
                            "question": verification_question,
                        }
                        pending_call = self._safe_confirmation_call(
                            name,
                            arguments,
                            planning_message,
                            verification_question,
                        )
                        if pending_call:
                            pending_state["pending_call"] = pending_call
                        _pending_nlu_context[user_id] = pending_state
                    return verification_question

                if user_id:
                    _pending_nlu_context.pop(user_id, None)
                result = await execute_tool(name, arguments)
                parts.append(self._format_tool_result(name, result))

            reply = "\n\n".join(part for part in parts if part).strip()
            return sanitize_chat_reply(reply) or await ai_reply(user_message)

    def _normalized_reply(self, message: str) -> str:
        return re.sub(r"[.!?]+$", "", message.strip().lower()).strip()

    def _starts_new_request(
        self,
        message: str,
        pending: dict[str, Any],
    ) -> bool:
        requested_tool = self._explicit_request_tool(message)
        if not requested_tool:
            return False
        pending_tool = str(pending.get("predicted_tool") or "")
        return not pending_tool or requested_tool != pending_tool

    def _merge_pending_reply(
        self,
        original: str,
        reply: str,
        pending: dict[str, Any],
    ) -> str:
        missing_slots = set(pending.get("missing_slots") or [])
        if missing_slots == {"time_period"}:
            match = re.search(
                r"(?:a\.?m\.?|p\.?m\.?)\b|"
                r"\b(?:morning|afternoon|evening|tonight)\b",
                reply,
                flags=re.IGNORECASE,
            )
            if match:
                return f"{original} {match.group(0)}".strip()
        return f"{original} {reply}".strip()

    def _is_repeat_clarification(
        self,
        pending: dict[str, Any],
        question: str,
        missing_slots: list[str],
    ) -> bool:
        """True when we are about to re-ask the clarification just answered."""

        prev_question = self._normalized_reply(str(pending.get("question") or ""))
        new_question = self._normalized_reply(question)
        if prev_question and new_question and prev_question == new_question:
            return True
        prev_missing = set(pending.get("missing_slots") or [])
        return bool(prev_missing) and prev_missing == set(missing_slots or [])

    def _loop_break_message(self, pending: dict[str, Any]) -> str:
        if "time_period" in set(pending.get("missing_slots") or []):
            return (
                "I still couldn't work out the times. Send the whole event in "
                "one message with AM or PM — for example: "
                '"add bible study Sunday 9 pm to 10 pm".'
            )
        return (
            "Let's start over. Tell me what you need in one message, including "
            "the event name, date, and time range — for example: "
            '"add bible study Sunday 9 pm to 10 pm".'
        )

    def _explicit_request_tool(self, message: str) -> str | None:
        lower = message.strip().lower()
        if re.search(r"\b(?:move|reschedule|shift)\b", lower):
            return "move_calendar_block"
        if self._is_delete_request(lower):
            return "delete_calendar_block"
        if self._looks_like_calendar_block_request(lower) or re.fullmatch(
            r"(?:please\s+)?(?:help me\s+)?plan\s+.+",
            lower,
        ):
            return "add_calendar_block"
        if re.search(
            r"\b(?:what|which|show|list|tell me|do i have|what's|whats)\b"
            r".*\b(?:due|deadlines?|homework|assignments?|tasks?|submit)\b",
            lower,
        ):
            return "get_tasks"
        if re.search(
            r"\b(?:what|which|show|list|do i have|what's|whats)\b"
            r".*\b(?:calendar|schedule|classes?|meetings?|events?|lectures?|labs?)\b",
            lower,
        ):
            return "get_calendar_events"
        if re.search(r"\b(?:schedule|reserve|make time|block time)\b", lower):
            return "propose_schedule_change"
        if re.search(
            r"\b(?:free time|free slots?|open time|availability|when am i free)\b",
            lower,
        ):
            return "find_free_slots"
        if re.fullmatch(
            r"(?:hi|hello|hey|thanks|thank you|good morning|good afternoon|"
            r"good evening)[.!?]*",
            lower,
        ) or re.search(
            r"\b(?:tell me|write|explain|summarize|brainstorm|translate|"
            r"i feel|i am feeling|i'm feeling)\b",
            lower,
        ):
            return "ai_agent"
        if re.match(
            r"(?:what|why|how|who|where|can you|could you|would you|please)\b",
            lower,
        ):
            return "ai_agent"
        return None

    def _is_move_request(self, text: str) -> bool:
        return bool(
            re.search(r"\b(?:move|reschedule|shift)\b", text, flags=re.IGNORECASE)
        )

    def _message_has_clock_time(self, text: str) -> bool:
        """True if the message names a specific clock time (10:30, 10pm, at 11)."""
        return bool(
            re.search(
                r"\b\d{1,2}:\d{2}\b"
                r"|\b\d{1,2}\s*(?:a\.?m\.?|p\.?m\.?)\b"
                r"|\bat\s+\d{1,2}\b",
                text,
                flags=re.IGNORECASE,
            )
        )

    # Pronouns/adverbs that aren't real event names ("move it", "move on").
    _NON_TITLE_WORDS = {"it", "that", "this", "them", "those", "on", "forward", "ahead", "along"}

    def _extract_move_title(self, message: str) -> str:
        """Pull the event name out of "move my gaming to friday" phrasing."""

        match = re.search(
            r"\b(?:move|reschedule|shift)\b\s+(?:my|the|this|that|a|an)?\s*(.+)$",
            message.strip(),
            flags=re.IGNORECASE,
        )
        if not match:
            return ""
        title = match.group(1)
        # Cut at the target ("... to friday") or any trailing date/time phrase.
        title = re.split(
            r"\b(?:to|on|at|from|for|today|tomorrow|tonight|monday|tuesday|"
            r"wednesday|thursday|friday|saturday|sunday|this week|next week)\b",
            title,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        title = " ".join(title.strip(" .,:;-").split())
        if title.lower() in self._NON_TITLE_WORDS:
            return ""
        return title

    def _is_delete_request(self, text: str) -> bool:
        return bool(
            re.search(
                r"\b(?:delete|remove|cancel|get rid of|take off)\b",
                text,
                flags=re.IGNORECASE,
            )
        )

    def _extract_delete_title(self, message: str) -> str:
        """Pull the event name out of "delete my X" / "remove the X today"."""

        match = re.search(
            r"\b(?:delete|remove|cancel|get rid of|take off)\b\s+"
            r"(?:my|the|this|that|a|an)?\s*(.+)$",
            message.strip(),
            flags=re.IGNORECASE,
        )
        if not match:
            return ""
        title = match.group(1)
        # Drop a trailing date/time phrase ("... today", "... from my calendar").
        title = re.split(
            r"\b(?:from|on|at|for|today|tomorrow|tonight|monday|tuesday|"
            r"wednesday|thursday|friday|saturday|sunday|this week|next week)\b",
            title,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0]
        return " ".join(title.strip(" .,:;-").split())

    def _coerce_delete_intent(
        self,
        name: str,
        arguments: dict[str, Any],
        message: str,
    ) -> tuple[str, dict[str, Any]]:
        """Reroute to delete_calendar_block when the user asks to remove an event.

        The trained router has no delete tool, so a "delete my bible study"
        message arrives as add_calendar_block, ai_agent, or a clarification.
        When the message is clearly a delete request and names an existing
        block, run the delete instead.
        """

        if name == "delete_calendar_block":
            return name, arguments
        if not self._is_delete_request(message):
            return name, arguments

        title_query = self._extract_delete_title(message) or str(
            arguments.get("title") or arguments.get("title_query") or ""
        ).strip()
        # Only reroute when we can actually find the event; otherwise let the
        # normal flow answer or ask, rather than deleting the wrong thing.
        if not title_query:
            return name, arguments
        if not chat_agent_tools.matching_study_blocks(title_query):
            return name, arguments
        return "delete_calendar_block", {"title_query": title_query}

    def _coerce_move_intent(
        self,
        name: str,
        arguments: dict[str, Any],
        message: str,
    ) -> tuple[str, dict[str, Any]]:
        """Reroute to a move when the user clearly says 'move'.

        The trained router mislabels "move X to <day>" all over the place —
        add_calendar_block (would duplicate), ai_agent (just chats), or even a
        get_tasks/get_assignments clarification ("check Canvas?"). Whenever the
        message is a move request that names an existing block and a target day,
        rebuild the call as move_calendar_block so the block is relocated.
        """

        if name == "move_calendar_block":
            return name, arguments
        if not self._is_move_request(message):
            return name, arguments

        title_query = str(
            arguments.get("title")
            or arguments.get("task_name")
            or arguments.get("title_query")
            or ""
        ).strip()
        # Non-calendar plans (ai_agent, get_tasks, ...) carry no title slot —
        # pull it from the user's words.
        if not title_query:
            title_query = self._extract_move_title(message)
        if not title_query:
            return name, arguments
        # Only reroute when we can actually find the block the user means;
        # otherwise let the original path ask for clarification.
        if not chat_agent_tools.matching_study_blocks(title_query):
            return name, arguments

        start_dt = self._parse_naive_datetime(arguments.get("start_time"))
        end_dt = self._parse_naive_datetime(arguments.get("end_time"))
        # The user gave a clock time but the router hasn't resolved it into
        # start/end yet (e.g. it asked AM/PM). Don't move with the wrong time —
        # let that flow resolve first; the resolved add then re-routes here.
        if start_dt is None and self._message_has_clock_time(message):
            return name, arguments
        # The router fills start/end using the *source* date for phrasing like
        # "move X tomorrow to today" (it grabs the first date it sees). Trust the
        # user's own words for the target day and reuse only the time-of-day.
        target_day = self._move_target_date(message) or (
            start_dt.date() if start_dt else None
        )
        # Need a concrete target day before moving — guards against non-calendar
        # phrases like "move on to the next topic" that have no date.
        if target_day is None:
            return name, arguments

        moved_args: dict[str, Any] = {
            "title_query": title_query or "study block",
            "target_date": target_day.isoformat() if target_day else "",
        }
        # Preserve an explicit new time range on the target day; otherwise the
        # move keeps the block's existing time.
        if start_dt and end_dt and target_day:
            moved_args["start_time"] = datetime.combine(
                target_day, start_dt.time()
            ).isoformat()
            moved_args["end_time"] = datetime.combine(
                target_day, end_dt.time()
            ).isoformat()
        return "move_calendar_block", moved_args

    _WEEKDAY_TOKENS = {
        "monday": 0, "mon": 0,
        "tuesday": 1, "tues": 1, "tue": 1,
        "wednesday": 2, "wed": 2,
        "thursday": 3, "thurs": 3, "thur": 3, "thu": 3,
        "friday": 4, "fri": 4,
        "saturday": 5, "sat": 5,
        "sunday": 6, "sun": 6,
    }

    def _parse_naive_datetime(self, value: object) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(
                tzinfo=None
            )
        except ValueError:
            return None

    def _move_target_date(self, message: str) -> date | None:
        """Resolve the day the user wants to move an event ONTO.

        For "move X <source> to <target> at <time>" the target is the last
        day token before the time range, so take the last date token in the
        message (times like "8pm" are never date tokens).
        """

        tokens = re.findall(
            r"\b(today|tomorrow|monday|mon|tuesday|tues|tue|wednesday|wed|"
            r"thursday|thurs|thur|thu|friday|fri|saturday|sat|sunday|sun|"
            r"\d{4}-\d{2}-\d{2})\b",
            message.lower(),
        )
        if not tokens:
            return None
        return self._resolve_date_token(tokens[-1])

    def _resolve_date_token(self, token: str) -> date | None:
        token = token.strip().lower()
        today = effective_today()
        if token == "today":
            return today
        if token == "tomorrow":
            return today + timedelta(days=1)
        if token in self._WEEKDAY_TOKENS:
            delta = (self._WEEKDAY_TOKENS[token] - today.weekday()) % 7
            return today + timedelta(days=delta)
        try:
            return date.fromisoformat(token[:10])
        except ValueError:
            return None

    def _safe_confirmation_call(
        self,
        name: str,
        arguments: dict[str, Any],
        user_message: str,
        question: str,
    ) -> dict[str, Any] | None:
        if not question.lower().startswith("do you want me to"):
            return None
        lower = user_message.lower()
        if name == "add_calendar_block":
            title = str(arguments.get("title") or "").strip().lower()
            if title and title in lower and self._verify_add_calendar_block(arguments) is None:
                return {"name": name, "arguments": dict(arguments)}
        if name == "move_calendar_block":
            title = str(arguments.get("title_query") or "").strip().lower()
            if title and title in lower and str(arguments.get("target_date") or "").strip():
                return {"name": name, "arguments": dict(arguments)}
        return None

    async def _ai_agent_reply(
        self,
        client: httpx.AsyncClient,
        message: str,
        *,
        history: list[dict[str, str]] | None = None,
    ) -> str:
        ai_result = (
            await self._call_ai_agent(client, message, history=history)
            if history
            else await self._call_ai_agent(client, message)
        )
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
            if self._is_move_request(lower):
                return (
                    "I could not find that event in your calendar preview to move. "
                    "What is the exact name of the block you want to move?"
                )
            if self._is_delete_request(lower):
                return (
                    "I could not find that event in your calendar to delete. "
                    "What is the exact name of the event you want to remove?"
                )
            if not (
                self._looks_like_calendar_block_request(lower)
                or self._looks_like_calendar_block_details(lower)
            ):
                return (
                    "Do you want me to add a calendar block? If so, send the "
                    "event name, date, start time, and end time."
                )
            return self._verify_add_calendar_block(arguments)
        if name == "move_calendar_block":
            if not self._has_any(lower, ("move", "reschedule", "shift")):
                return "Do you want me to move an existing study block?"
            target_date = str(arguments.get("target_date") or "").strip()
            if not target_date:
                return "What date should I move this study block to?"
            matches = chat_agent_tools.matching_study_blocks(
                arguments.get("title_query") or "study block"
            )
            if not matches:
                return (
                    "I could not find that study block in your calendar preview. "
                    "What is the block name?"
                )
            # Only ask "which one?" for genuinely different events. Duplicate
            # same-title blocks can't be told apart by name, so the tool picks
            # one deterministically instead of looping on the question.
            if chat_agent_tools.resolve_single_block(matches) is None:
                titles = ", ".join(
                    sorted(
                        {
                            str(block.get("title") or "Study block").strip()
                            for block in matches
                        }
                    )
                )
                return f"Which study block should I move? I found: {titles}."
            return None
        if name == "propose_schedule_change":
            if self._looks_like_calendar_block_details(lower):
                return (
                    "I found an event name, date, and time range. Should I add "
                    "it as a calendar block?"
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
        direct_range = (
            r"\b\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?\s*"
            r"(?:-|to|until|through)\s*"
            r"\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?\b"
        )
        between_range = (
            r"\b(?:sometime\s+)?between\s+"
            r"\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?\s+and\s+"
            r"\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?\b"
        )
        labeled_range = (
            r"\b(?:with\s+(?:a\s+)?)?"
            r"(?:starting|starts?|start(?:\s+time)?(?:\s+(?:is|of))?)\s+"
            r"(?:at\s+|of\s+)?"
            r"\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?\s*"
            r"(?:,|and|then)?\s*"
            r"(?:ending|ends?|end(?:\s+time)?(?:\s+(?:is|of))?)\s+"
            r"(?:at\s+|of\s+)?"
            r"\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?\b"
        )
        duration_range = (
            r"\b(?:at|from|starting\s+at|starts?\s+at)\s+"
            r"\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?"
            r"(?:\s+in\s+(?:the\s+)?(?:morning|afternoon|evening)|\s+tonight)?"
            r"\s+for\s+"
            r"(?:\d+(?:\.\d+)?|an?|one|two|three|four|five|six|seven|eight|"
            r"nine|ten|eleven|twelve|fifteen|twenty|thirty|forty(?:-five)?|"
            r"sixty|ninety|half(?:\s+an?)?|"
            r"quarter(?:\s+of\s+an?)?)\s*"
            r"(?:hours?|hrs?|hr|h|minutes?|mins?|min|m)\b"
        )
        has_time_range_text = bool(
            re.search(
                rf"(?:{direct_range}|{between_range}|{labeled_range}|{duration_range})",
                text,
                flags=re.IGNORECASE,
            )
        )
        has_time_period = bool(
            re.search(
                r"(?:a\.?m\.?|p\.?m\.?)\b|"
                r"\b(?:morning|afternoon|evening|tonight)\b",
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
        return has_time_range_text and has_time_period and has_date

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
        *,
        history: list[dict[str, str]] | None = None,
    ) -> dict[str, Any]:
        try:
            host = self._ai_agent_host()
        except RuntimeError as exc:
            return {"error": str(exc), "message": message}

        url = f"{host}/api/generate"
        payload = {
            "model": self._ai_agent_model(),
            "prompt": self._ai_agent_prompt(message, history),
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

    def _ai_agent_prompt(
        self,
        message: str,
        history: list[dict[str, str]] | None,
    ) -> str:
        if not history:
            return message
        lines = [
            "Use this recent conversation only as context. Answer the current user request.",
            "",
        ]
        for item in history[-12:]:
            role = str(item.get("role") or "user").strip().capitalize()
            content = str(item.get("content") or "").strip()
            if content:
                lines.append(f"{role}: {content}")
        lines.extend(("", f"Current user request: {message}"))
        return "\n".join(lines)

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
        if name == "move_calendar_block":
            return self._format_move_calendar_block(result)
        if name == "delete_calendar_block":
            return self._format_delete_calendar_block(result)
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

    def _format_move_calendar_block(self, result: dict[str, Any]) -> str:
        message = str(result.get("message") or "").strip()
        proposal = result.get("proposal") if isinstance(result.get("proposal"), list) else []
        if not proposal:
            return message or "I could not move that study block."
        lines = [message or "I moved that study block."]
        for block in proposal[:1]:
            if not isinstance(block, dict):
                continue
            title = block.get("task_title") or "Study block"
            start = self._short_time(block.get("start_time"))
            end = self._short_time(block.get("end_time"))
            lines.append(f"- {title}: {start} to {end}")
        return "\n".join(lines)

    def _format_delete_calendar_block(self, result: dict[str, Any]) -> str:
        message = str(result.get("message") or "").strip()
        proposal = result.get("proposal") if isinstance(result.get("proposal"), list) else []
        if not proposal:
            # No match / ambiguous — the tool's message is the question to ask.
            return message or "I could not delete that event."
        return message or "I removed that event from your calendar."

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
