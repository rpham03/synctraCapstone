"""Chat service backed by the trained NLP tool router."""

from __future__ import annotations

import os
import re
from datetime import date, datetime, time, timedelta
from typing import Any

import httpx

from app.core.config.settings import settings
from app.services import chat_agent_tools, productivity_preferences
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
    "set_productivity_preferences",
    "get_productivity_preferences",
    "remove_productivity_preferences",
    "classify_all_calendar_events",
    "classify_calendar_item",
    "set_event_flexibility_override",
    "suggest_preference_schedule",
    "apply_preference_schedule",
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

        if pending and self._starts_new_request(user_message, pending):
            if user_id:
                _pending_nlu_context.pop(user_id, None)
            pending = None

        if pending and isinstance(pending.get("delete_disambiguation"), dict):
            return await self._continue_pending_delete_selection(
                user_message,
                pending,
                user_id=user_id,
            )

        # Productivity preferences + classification are backend-only intents the
        # trained router doesn't know — handle them deterministically first.
        preference_reply = await self._maybe_handle_preferences(
            user_message, pending, user_id=user_id
        )
        if preference_reply is not None:
            return preference_reply

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
                name, arguments = self._coerce_resize_intent(
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

                delete_disambiguation = (
                    self._delete_disambiguation_state(arguments)
                    if name == "delete_calendar_block"
                    else None
                )
                if delete_disambiguation:
                    question = self._delete_choice_question(delete_disambiguation)
                    if user_id:
                        _pending_nlu_context[user_id] = {
                            "message": planning_message,
                            "slots": {},
                            "missing_slots": ["event_selection"],
                            "predicted_tool": name,
                            "question": question,
                            "delete_disambiguation": delete_disambiguation,
                        }
                    return question

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

    def _delete_disambiguation_state(
        self,
        arguments: dict[str, Any],
    ) -> dict[str, Any] | None:
        """Build safe choice state when one or more delete names are duplicated."""

        if bool(arguments.get("delete_all_matches")):
            return None
        raw_queries = arguments.get("title_queries")
        queries = [
            str(value).strip()
            for value in raw_queries
            if str(value).strip()
        ] if isinstance(raw_queries, list) else []
        if not queries:
            query = str(arguments.get("title_query") or "").strip()
            if query:
                queries = [query]

        resolved_ids: list[str] = []
        groups: list[dict[str, Any]] = []
        for query in queries:
            matches = chat_agent_tools.matching_study_blocks(
                query,
                start_date=arguments.get("start_date") or "",
                end_date=arguments.get("end_date") or "",
            )
            if " ".join(query.lower().split()) in {
                "study block",
                "study blocks",
                "study time",
            }:
                matches = [
                    block
                    for block in matches
                    if str(block.get("source") or "").lower() == "study_block"
                ]
            candidates = [
                self._delete_candidate(block)
                for block in matches
                if str(block.get("id") or "").strip()
            ]
            if len(candidates) > 1:
                groups.append({"query": query, "candidates": candidates})
            elif len(candidates) == 1:
                resolved_ids.append(str(candidates[0]["id"]))

        if not groups:
            return None
        return {
            "groups": groups,
            "selected_ids": list(dict.fromkeys(resolved_ids)),
        }

    def _delete_candidate(self, block: dict[str, Any]) -> dict[str, str]:
        start = self._parse_naive_datetime(block.get("start_time"))
        day = chat_agent_tools._event_local_date(block)
        return {
            "id": str(block.get("id") or "").strip(),
            "title": str(block.get("title") or "Event").strip() or "Event",
            "date": day.isoformat() if day else "",
            "day_label": day.strftime("%A, %b ") + str(day.day) if day else "unknown date",
            "time_label": start.strftime("%I:%M %p").lstrip("0") if start else "unknown time",
            "start_time": start.isoformat() if start else "",
        }

    def _delete_choice_question(self, state: dict[str, Any], *, retry: bool = False) -> str:
        groups = state.get("groups")
        group = groups[0] if isinstance(groups, list) and groups else {}
        query = str(group.get("query") or "event")
        candidates = group.get("candidates")
        choices = candidates if isinstance(candidates, list) else []
        details = "; ".join(
            f"{index}. {candidate.get('title', 'Event')} on "
            f"{candidate.get('day_label', 'unknown date')} at "
            f"{candidate.get('time_label', 'unknown time')}"
            for index, candidate in enumerate(choices, start=1)
            if isinstance(candidate, dict)
        )
        prefix = "I still need a specific choice. " if retry else ""
        return (
            f"{prefix}I found multiple matches for {query}: {details}. "
            "Which one should I remove? Reply with the number, date, time, "
            f"or say \"all {query}\"."
        )

    async def _continue_pending_delete_selection(
        self,
        reply: str,
        pending: dict[str, Any],
        *,
        user_id: str | None,
    ) -> str:
        state = pending.get("delete_disambiguation")
        if not isinstance(state, dict):
            return "Which event should I remove?"
        groups = state.get("groups")
        if not isinstance(groups, list) or not groups:
            if user_id:
                _pending_nlu_context.pop(user_id, None)
            return "Which event should I remove?"

        group = groups[0] if isinstance(groups[0], dict) else {}
        raw_candidates = group.get("candidates")
        candidates = [
            candidate
            for candidate in raw_candidates
            if isinstance(candidate, dict)
        ] if isinstance(raw_candidates, list) else []
        selected = self._select_delete_candidates(reply, candidates)
        if not selected:
            question = self._delete_choice_question(state, retry=True)
            pending["question"] = question
            if user_id:
                _pending_nlu_context[user_id] = pending
            return question

        selected_ids = [
            str(value)
            for value in state.get("selected_ids") or []
            if str(value).strip()
        ]
        selected_ids.extend(str(candidate.get("id") or "") for candidate in selected)
        state["selected_ids"] = list(dict.fromkeys(value for value in selected_ids if value))
        groups.pop(0)
        state["groups"] = groups
        if groups:
            question = self._delete_choice_question(state)
            pending["question"] = question
            pending["delete_disambiguation"] = state
            if user_id:
                _pending_nlu_context[user_id] = pending
            return question

        if user_id:
            _pending_nlu_context.pop(user_id, None)
        result = await execute_tool(
            "delete_calendar_block",
            {
                "title_query": "event",
                "delete_block_ids": state["selected_ids"],
            },
        )
        return sanitize_chat_reply(self._format_tool_result("delete_calendar_block", result))

    def _select_delete_candidates(
        self,
        reply: str,
        candidates: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        lower = self._normalized_reply(reply)
        if re.search(r"\b(?:all|both|every|each)\b", lower):
            return candidates

        ordinal_words = {
            "first": 1,
            "second": 2,
            "third": 3,
            "fourth": 4,
            "fifth": 5,
            "sixth": 6,
        }
        number_match = re.search(r"\b(?:number\s*)?([1-6])\b", lower)
        choice = int(number_match.group(1)) if number_match else None
        if choice is None:
            for word, index in ordinal_words.items():
                if re.search(rf"\b{word}\b", lower):
                    choice = index
                    break
        if choice is not None and 1 <= choice <= len(candidates):
            return [candidates[choice - 1]]

        narrowed = candidates
        date_range = self._delete_date_range(reply)
        if date_range:
            start_date, end_date = date_range
            narrowed = [
                candidate
                for candidate in narrowed
                if start_date <= str(candidate.get("date") or "") <= end_date
            ]

        clock_minutes = self._reply_clock_minutes(reply)
        if clock_minutes is not None:
            narrowed = [
                candidate
                for candidate in narrowed
                if self._candidate_clock_minutes(candidate) == clock_minutes
            ]
        return narrowed if len(narrowed) == 1 else []

    def _reply_clock_minutes(self, message: str) -> int | None:
        match = re.search(
            r"\b(\d{1,2})(?::([0-5]\d))?\s*(a\.?m\.?|p\.?m\.?)\b",
            message,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        hour = int(match.group(1))
        minute = int(match.group(2) or 0)
        period = match.group(3).lower().replace(".", "")
        if not 1 <= hour <= 12:
            return None
        if period == "pm" and hour != 12:
            hour += 12
        elif period == "am" and hour == 12:
            hour = 0
        return hour * 60 + minute

    def _candidate_clock_minutes(self, candidate: dict[str, Any]) -> int | None:
        start = self._parse_naive_datetime(candidate.get("start_time"))
        return start.hour * 60 + start.minute if start else None

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
        """True if the message names a clock time (10:30, 10pm, "at 11", "to 7").

        The bare-hour forms ("move it to 7", "at 8") are accepted so a move can
        try to retime; the ordinal lookahead keeps "to the 7th"/"by the 12th"
        (calendar dates) from being mistaken for a time.
        """
        return bool(
            re.search(
                r"\b\d{1,2}:\d{2}\b"
                r"|\b\d{1,2}\s*(?:a\.?m\.?|p\.?m\.?)\b"
                r"|\b(?:at|to|by|till|until)\s+\d{1,2}\b(?!\s*(?:st|nd|rd|th))",
                text,
                flags=re.IGNORECASE,
            )
        )

    def _parse_clock_times(self, text: str) -> list[time]:
        """Unambiguous clock times in order (12h with AM/PM, or 24h HH:MM)."""

        out: list[time] = []
        for match in re.finditer(
            r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?",
            text,
            flags=re.IGNORECASE,
        ):
            hour = int(match.group(1))
            minute = int(match.group(2) or 0)
            ampm = (match.group(3) or "").replace(".", "").lower()
            if ampm:
                if not 1 <= hour <= 12 or minute > 59:
                    continue
                if ampm.startswith("p") and hour != 12:
                    hour += 12
                if ampm.startswith("a") and hour == 12:
                    hour = 0
            elif 13 <= hour <= 23 and minute <= 59:
                pass  # unambiguous 24-hour time
            else:
                continue  # bare hour without AM/PM is ambiguous — skip
            out.append(time(hour, minute))
        return out

    def _parse_bare_hours_after_prep(self, text: str) -> list[time]:
        """Bare hours that follow a time preposition ("to 7", "at 8 to 9").

        Used only as a move/retime fallback when no unambiguous clock time was
        given. A bare hour is read as PM (the usual intent for "move it to 7"),
        so 1-11 -> afternoon/evening and 12 stays noon. The ordinal lookahead
        skips calendar dates like "to the 12th".
        """

        out: list[time] = []
        for match in re.finditer(
            r"\b(?:at|to|by|till|until)\s+(\d{1,2})(?::(\d{2}))?\b"
            r"(?!\s*(?:st|nd|rd|th|a\.?m\.?|p\.?m\.?))",
            text,
            flags=re.IGNORECASE,
        ):
            hour = int(match.group(1))
            minute = int(match.group(2) or 0)
            if hour > 23 or minute > 59:
                continue
            if 1 <= hour <= 11:
                hour += 12  # assume PM
            out.append(time(hour % 24, minute))
        return out

    def _retime_block(
        self, message: str, block: dict[str, Any]
    ) -> tuple[datetime, datetime] | None:
        """Compute a moved block's new start/end from times in the message."""

        cur_start = self._parse_naive_datetime(block.get("start_time"))
        cur_end = self._parse_naive_datetime(block.get("end_time"))
        if cur_start is None or cur_end is None:
            return None
        duration = cur_end - cur_start
        day = self._move_target_date(message) or cur_start.date()
        times = self._parse_clock_times(message)
        if not times:
            # No unambiguous time — accept a bare hour after "to"/"at" ("to 7").
            times = self._parse_bare_hours_after_prep(message)
        if not times:
            return None
        # "move X from <src> to <dst>" relocates to the dst time, keeping length.
        if re.search(r"\bfrom\b", message, flags=re.IGNORECASE) and len(times) >= 2:
            new_start = datetime.combine(day, times[-1])
            return new_start, new_start + duration
        # An explicit new range ("... 8pm to 9pm").
        if len(times) >= 2:
            new_start = datetime.combine(day, times[0])
            new_end = datetime.combine(day, times[1])
            if new_end <= new_start:
                new_end = new_start + duration
            return new_start, new_end
        # A single new start time, keep the length.
        new_start = datetime.combine(day, times[0])
        return new_start, new_start + duration

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
                r"\b(?:delete|remove|cancel|erase|drop|clear|get rid of|"
                r"take off|take\b.+\boff)\b",
                text,
                flags=re.IGNORECASE,
            )
        )

    def _extract_delete_titles(self, message: str) -> list[str]:
        """Pull one or more event names out of natural delete phrasing."""

        take_match = re.search(
            r"\btake\s+(.+?)\s+off(?:\s+(?:my|the)\s+(?:calendar|schedule))?\b",
            message.strip(),
            flags=re.IGNORECASE,
        )
        if take_match:
            cleaned = take_match.group(1)
        else:
            match = re.search(
                r"\b(?:delete|remove|cancel|erase|drop|clear|get rid of|take off)\b"
                r"\s+(.+)$",
                message.strip(),
                flags=re.IGNORECASE,
            )
            if not match:
                return []
            cleaned = match.group(1)
        cleaned = re.sub(
            r"\b(?:from|off|out of)\s+(?:my|the)?\s*(?:calendar|schedule)\b",
            " ",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"\b(?:today|tomorrow|tonight|this week|next week|this weekend|"
            r"next weekend|weekend|monday|mon|tuesday|tue|wednesday|wed|"
            r"thursday|thu|friday|fri|saturday|sat|sunday|sun|"
            r"\d{4}-\d{2}-\d{2})\b",
            " ",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"^\s*(?:please\s+)?(?:all|every|each|both|my|the|this|that|a|an)\s+",
            " ",
            cleaned,
            flags=re.IGNORECASE,
        )
        normalized = " ".join(cleaned.strip(" .,:;!?-").split())
        if normalized.lower() in {
            "",
            "event",
            "events",
            "calendar event",
            "calendar events",
            "calendar",
            "schedule",
            "appointment",
            "appointments",
            "block",
            "blocks",
            "calendar block",
            "calendar blocks",
            "everything",
        }:
            return []
        titles: list[str] = []
        for part in re.split(r"\s*,\s*(?:and\s+)?|\s+and\s+", normalized):
            title = re.sub(
                r"^\s*(?:all|every|each|both|my|the|this|that|a|an)\s+",
                " ",
                part,
                flags=re.IGNORECASE,
            )
            title = " ".join(title.strip(" .,:;!?-").split())
            if title and title.lower() not in {"event", "events", "block", "blocks"}:
                titles.append(title[:120])
        return list(dict.fromkeys(titles))

    def _wants_delete_all(self, message: str) -> bool:
        return bool(
            re.search(
                r"\b(?:all|every|everything|entire|each)\b",
                message,
                flags=re.IGNORECASE,
            )
            or re.search(
                r"\bclear\s+(?:out\s+)?(?:my|the)?\s*(?:calendar|schedule)\b",
                message,
                flags=re.IGNORECASE,
            )
        )

    def _delete_date_range(self, message: str) -> tuple[str, str] | None:
        lower = message.lower()
        today = effective_today()
        if "tomorrow" in lower:
            day = today + timedelta(days=1)
            return day.isoformat(), day.isoformat()
        if "today" in lower or "tonight" in lower:
            return today.isoformat(), today.isoformat()
        if "next week" in lower:
            monday = today - timedelta(days=today.weekday()) + timedelta(days=7)
            return monday.isoformat(), (monday + timedelta(days=4)).isoformat()
        if "this week" in lower:
            monday = today - timedelta(days=today.weekday())
            return monday.isoformat(), (monday + timedelta(days=4)).isoformat()
        if "weekend" in lower:
            saturday = today - timedelta(days=today.weekday()) + timedelta(days=5)
            if "next weekend" in lower:
                saturday += timedelta(days=7)
            return saturday.isoformat(), (saturday + timedelta(days=1)).isoformat()
        named_date = re.search(
            r"\b(january|jan|february|feb|march|mar|april|apr|may|june|jun|"
            r"july|jul|august|aug|september|sep|sept|october|oct|"
            r"november|nov|december|dec)\s+(\d{1,2})(?:st|nd|rd|th)?"
            r"(?:,\s*(\d{4}))?\b",
            lower,
        )
        if named_date:
            months = {
                "jan": 1,
                "feb": 2,
                "mar": 3,
                "apr": 4,
                "may": 5,
                "jun": 6,
                "jul": 7,
                "aug": 8,
                "sep": 9,
                "oct": 10,
                "nov": 11,
                "dec": 12,
            }
            try:
                day = date(
                    int(named_date.group(3) or today.year),
                    months[named_date.group(1)[:3]],
                    int(named_date.group(2)),
                )
                return day.isoformat(), day.isoformat()
            except ValueError:
                return None
        numeric_date = re.search(
            r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b",
            lower,
        )
        if numeric_date:
            year_text = numeric_date.group(3)
            year = int(year_text) if year_text else today.year
            if year_text and len(year_text) == 2:
                year += 2000
            try:
                day = date(year, int(numeric_date.group(1)), int(numeric_date.group(2)))
                return day.isoformat(), day.isoformat()
            except ValueError:
                return None
        tokens = re.findall(
            r"\b(monday|mon|tuesday|tue|wednesday|wed|thursday|thu|"
            r"friday|fri|saturday|sat|sunday|sun|\d{4}-\d{2}-\d{2})\b",
            lower,
        )
        if tokens:
            day = self._resolve_date_token(tokens[-1])
            if day:
                return day.isoformat(), day.isoformat()
        return None

    # ---- productivity preferences + classification (backend-only intents) ----

    _PRODUCTIVE_CUE = re.compile(
        r"\b(?:productive|productivity|work[s]? best|focus(?:es)? best|"
        r"most productive|preferred (?:productive )?(?:time|period|hours)|"
        r"productivity preference)\b",
        re.IGNORECASE,
    )

    def _infer_period(self, start: time) -> str:
        """Map a start hour to a productive period bucket."""
        hour = start.hour
        if 6 <= hour < 12:
            return "morning"
        if 12 <= hour < 17:
            return "afternoon"
        if 17 <= hour < 21:
            return "evening"
        return "night"

    def _preference_set_args(self, message: str) -> tuple[list[str], str, str]:
        """Extract productive periods and an optional custom time window.

        Handles "I'm productive at night", "I'm productive from 8pm to 11pm"
        (period inferred from the start time), and combinations.
        """
        periods = productivity_preferences.detect_periods(message.lower())
        times = self._parse_clock_times(message)
        start_str = end_str = ""
        if len(times) >= 2:
            start_str = f"{times[0].hour:02d}:{times[0].minute:02d}"
            end_str = f"{times[1].hour:02d}:{times[1].minute:02d}"
            if not periods:
                periods = [self._infer_period(times[0])]
        return periods, start_str, end_str

    async def _save_preference(
        self,
        message: str,
        periods: list[str],
        start_str: str,
        end_str: str,
        *,
        user_id: str | None,
    ) -> str:
        args: dict[str, Any] = {"periods": periods}
        if start_str and end_str:
            args["start_time"] = start_str
            args["end_time"] = end_str
        result = await execute_tool("set_productivity_preferences", args)
        if user_id:
            _pending_nlu_context[user_id] = {
                "message": message,
                "predicted_tool": "suggest_preference_schedule",
                "awaiting_preference_suggest": True,
                "periods": periods,
            }
        return sanitize_chat_reply(self._format_set_preferences(result, periods))

    _RETRY_TARGETS = (
        "again", "another", "different", "regenerate", "reshuffle", "shuffle", "retry",
    )

    @staticmethod
    def _levenshtein(a: str, b: str) -> int:
        if a == b:
            return 0
        if not a:
            return len(b)
        if not b:
            return len(a)
        prev = list(range(len(b) + 1))
        for i, ca in enumerate(a, start=1):
            cur = [i]
            for j, cb in enumerate(b, start=1):
                cur.append(
                    min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
                )
            prev = cur
        return prev[-1]

    @classmethod
    def _close_enough(cls, candidate: str, target: str) -> bool:
        threshold = 1 if len(target) <= 4 else 2
        if abs(len(candidate) - len(target)) > threshold:
            return False
        return cls._levenshtein(candidate, target) <= threshold

    def _is_retry_reply(self, text: str) -> bool:
        lowered = text.lower()
        if re.search(
            r"\b(?:try again|another|different|regenerate|redo|reshuffle|"
            r"shuffle|retry|other option|other options|something else|"
            r"not these|not those|mix it up|new schedule|different schedule|"
            r"different one|another one|other schedule)\b",
            lowered,
            flags=re.IGNORECASE,
        ):
            return True
        # Typo-tolerant for terse replies ("try aain", "try agian", "anther").
        words = re.findall(r"[a-z]+", lowered)
        if not words or len(words) > 4:
            return False
        compact = "".join(words)
        if any(
            self._close_enough(compact, target)
            for target in ("tryagain", "tryanother", "retry", "reshuffle", "shuffle", "regenerate")
        ):
            return True
        return any(
            self._close_enough(word, target)
            for word in words
            if len(word) >= 4
            for target in self._RETRY_TARGETS
        )

    def _is_bare_retry(self, text: str) -> bool:
        """A terse retry ("try again", "another", "try aain") with no other words.

        Used only to catch a retry when nothing is pending, so it must not fire
        for longer phrases like "schedule another study block".
        """
        words = re.findall(r"[a-z]+", text.lower())
        if not words or len(words) > 3:
            return False
        compact = "".join(words)
        return any(
            self._close_enough(compact, target)
            for target in ("tryagain", "retry", "regenerate", "reshuffle", "shuffle", "again")
        )

    def _is_apply_reply(self, text: str) -> bool:
        """A confirmation that should apply the pending schedule proposal."""
        norm = self._normalized_reply(text)
        if norm in _AFFIRMATIVE_REPLIES:
            return True
        return bool(
            re.search(
                r"\b(?:apply|use (?:it|these|them|this|that)|go ahead|looks good|"
                r"sounds good|that works|works for me|perfect|lock (?:it|them) in|"
                r"accept|add (?:it|them|these|those)|save (?:it|these|those)|"
                r"keep (?:it|these|those))\b",
                norm,
                flags=re.IGNORECASE,
            )
        )

    async def _offer_preference_schedule(
        self,
        message: str,
        *,
        seed: int | None,
        user_id: str | None,
        avoid: list | None = None,
    ) -> str:
        """Suggest a schedule and await apply/try-again.

        ``seed is None`` is the first suggestion (deterministic earliest). For a
        "try again" pass an incrementing ``seed`` and the ``avoid`` list of
        already-shown signatures; this searches seeds for a genuinely different
        arrangement and, if none exists, says so while keeping the last proposal
        pending so "yes" still applies it.
        """

        from app.services import preference_scheduler

        shown: set[tuple] = {tuple(sig) for sig in (avoid or [])}
        base = seed or 0
        result: dict[str, Any] | None = None

        if seed is None:
            result = preference_scheduler.suggest_preference_schedule(
                user_id=user_id, seed=None
            )
        else:
            last: dict[str, Any] | None = None
            for attempt in range(12):
                candidate = preference_scheduler.suggest_preference_schedule(
                    user_id=user_id, seed=base + attempt
                )
                last = candidate
                if not candidate.get("proposals"):
                    result = candidate
                    base += attempt
                    break
                if tuple(candidate.get("signature") or ()) not in shown:
                    result = candidate
                    base += attempt
                    break
            if result is None:
                # Every arrangement we found was one already shown.
                if user_id and shown:
                    pending = _pending_nlu_context.get(user_id)
                    if pending:
                        pending["seed"] = base + 11
                    return (
                        "That's the only schedule that fits your study window and "
                        'deadlines. Say "yes" to apply it, or widen your study window '
                        "in Settings for more options."
                    )
                result = last or {"proposals": [], "message": "Nothing to schedule."}

        proposals = result.get("proposals") or []
        if user_id and proposals:
            shown.add(tuple(result.get("signature") or ()))
            _pending_nlu_context[user_id] = {
                "message": message,
                "predicted_tool": "apply_preference_schedule",
                "awaiting_preference_apply": True,
                "preference_proposals": proposals,
                "seed": base,
                "shown_signatures": [list(sig) for sig in shown],
            }
        elif user_id:
            _pending_nlu_context.pop(user_id, None)
        return sanitize_chat_reply(self._format_schedule_suggestion(result))

    async def _maybe_handle_preferences(
        self,
        message: str,
        pending: dict[str, Any] | None,
        *,
        user_id: str | None,
    ) -> str | None:
        lower = message.strip().lower()
        norm = self._normalized_reply(message)

        # Follow-up to "apply these suggested times?" — write only on confirm.
        if pending and pending.get("awaiting_preference_apply"):
            # "try again" is checked before apply so a retry is never mistaken for
            # a confirmation, and never routed to the general AI agent.
            if self._is_retry_reply(lower):
                # Regenerate a genuinely different arrangement, excluding the ones
                # already shown this conversation.
                seed = int(pending.get("seed") or 0) + 1
                avoid = pending.get("shown_signatures") or []
                return await self._offer_preference_schedule(
                    message, seed=seed, user_id=user_id, avoid=avoid
                )
            if norm in _CANCEL_REPLIES:
                if user_id:
                    _pending_nlu_context.pop(user_id, None)
                return "Okay, I didn't change your calendar."
            if self._is_apply_reply(message):
                proposals = pending.get("preference_proposals") or []
                if user_id:
                    _pending_nlu_context.pop(user_id, None)
                if proposals:
                    from app.services.chat_client_context import append_schedule_proposals

                    append_schedule_proposals(proposals)
                    return f"Done — I applied {len(proposals)} block(s) to your calendar."
                return "There was nothing to apply."
            # A pending proposal exists but the reply isn't apply/try-again/cancel.
            # Keep the proposal and re-prompt instead of losing it to the AI agent.
            return (
                'I have a schedule ready. Say "yes" to apply it, "try again" for a '
                'different option, or "cancel".'
            )

        # Follow-up to "want me to suggest a schedule?" after saving a preference.
        if pending and pending.get("awaiting_preference_suggest"):
            if norm in _CANCEL_REPLIES:
                if user_id:
                    _pending_nlu_context.pop(user_id, None)
                return "Okay — your preference is saved. Just ask whenever you want a schedule."
            if self._is_apply_reply(message):
                return await self._offer_preference_schedule(
                    message, seed=None, user_id=user_id
                )

        # Follow-up to "which period?" — the user names a period (or a time range).
        if pending and pending.get("predicted_tool") == "set_productivity_preferences":
            periods, start_str, end_str = self._preference_set_args(message)
            if periods:
                return await self._save_preference(
                    message, periods, start_str, end_str, user_id=user_id
                )

        # A bare "try again"/"another" with no schedule pending — there's nothing
        # to redo, so ask what to schedule instead of guessing via the AI agent.
        if self._is_bare_retry(lower):
            return (
                "I don't have a schedule to redo yet. Tell me what to schedule — "
                'for example, "suggest a schedule for my tasks".'
            )

        has_cue = bool(self._PRODUCTIVE_CUE.search(lower)) or "preference" in lower

        # Remove preferences.
        if has_cue and re.search(r"\b(?:remove|clear|delete|forget|reset|drop)\b", lower):
            periods = productivity_preferences.detect_periods(lower)
            result = await execute_tool(
                "remove_productivity_preferences", {"periods": periods}
            )
            return sanitize_chat_reply(self._format_remove_preferences(result, periods))

        # Look up preferences.
        if has_cue and re.search(
            r"\b(?:what|what's|whats|show|list|tell me|when am i|do i have)\b", lower
        ):
            result = await execute_tool("get_productivity_preferences", {})
            return sanitize_chat_reply(self._format_get_preferences(result))

        # Save / set a preference.
        if has_cue:
            periods, start_str, end_str = self._preference_set_args(message)
            if not periods:
                if user_id:
                    _pending_nlu_context[user_id] = {
                        "message": message,
                        "predicted_tool": "set_productivity_preferences",
                        "missing_slots": ["period"],
                        "question": "Which time of day are you most productive?",
                    }
                return (
                    "Which time of day are you most productive — morning, "
                    "afternoon, evening, or night?"
                )
            return await self._save_preference(
                message, periods, start_str, end_str, user_id=user_id
            )

        # Mark an event fixed/flexible (explicit override).
        override = re.search(
            r"\b(?:mark|set|treat|make)\b\s+(?:my\s+|the\s+|this\s+)?(.+?)\s+"
            r"(?:as\s+)?(fixed|flexible)\b",
            message,
            flags=re.IGNORECASE,
        )
        if override:
            title = " ".join(override.group(1).strip(" .,:;-").split())
            result = await execute_tool(
                "set_event_flexibility_override",
                {"title": title, "flexibility": override.group(2).lower()},
            )
            return sanitize_chat_reply(self._format_override(result))

        # Classify the whole calendar.
        if (
            re.search(r"\bclassif", lower)
            and re.search(r"\b(?:all|calendar|events?|everything|schedule)\b", lower)
        ) or re.search(r"\b(?:what|which)\b.*\b(?:fixed|flexible)\b", lower):
            result = await execute_tool("classify_all_calendar_events", {})
            return sanitize_chat_reply(self._format_classify_all(result))

        # Classify a single event ("is my X fixed or flexible?", "classify X").
        one = re.search(
            r"\bis\s+(?:my\s+|the\s+)?(.+?)\s+(?:fixed|flexible)\b",
            message,
            flags=re.IGNORECASE,
        ) or re.search(r"\bclassify\s+(?:my\s+|the\s+)?(.+)$", message, flags=re.IGNORECASE)
        if one:
            title = " ".join(one.group(1).strip(" .,:;-?").split())
            if title:
                result = await execute_tool("classify_calendar_item", {"title": title})
                return sanitize_chat_reply(self._format_classify_one(result))

        return None

    def _format_period(self, pref: dict[str, str]) -> str:
        return (
            f"{pref['period']} "
            f"({self._short_clock(pref['start'])}–{self._short_clock(pref['end'])})"
        )

    def _short_clock(self, hhmm: str) -> str:
        try:
            hour, minute = (int(x) for x in str(hhmm).split(":"))
        except (ValueError, TypeError):
            return str(hhmm)
        suffix = "AM" if hour < 12 else "PM"
        h12 = hour % 12 or 12
        return f"{h12}:{minute:02d} {suffix}" if minute else f"{h12} {suffix}"

    def _join_periods(self, periods: list[str]) -> str:
        if len(periods) <= 1:
            return periods[0] if periods else "that time"
        return ", ".join(periods[:-1]) + f" and {periods[-1]}"

    def _format_set_preferences(self, result: dict[str, Any], periods: list[str]) -> str:
        if result.get("error"):
            return str(result["error"])
        label = self._join_periods(periods)
        return (
            f"I saved {label} as your preferred productive "
            f"{'periods' if len(periods) > 1 else 'period'}. Would you like me to "
            "suggest a schedule for your flexible tasks and events based on this "
            "preference?"
        )

    def _format_get_preferences(self, result: dict[str, Any]) -> str:
        prefs = result.get("preferences") or []
        if not prefs:
            return "You haven't set any productivity preferences yet."
        lines = ["You're most productive:"]
        for pref in prefs:
            lines.append(f"- {self._format_period(pref)}")
        return "\n".join(lines)

    def _format_remove_preferences(
        self, result: dict[str, Any], periods: list[str]
    ) -> str:
        if periods:
            return f"Removed your {self._join_periods(periods)} preference."
        return "Cleared your productivity preferences."

    def _format_override(self, result: dict[str, Any]) -> str:
        if result.get("error"):
            return str(result["error"])
        title = result.get("title") or "that event"
        return f"Got it — I'll treat {title} as {result.get('flexibility')}."

    def _format_classify_all(self, result: dict[str, Any]) -> str:
        counts = result.get("counts") or {}
        if not result.get("events"):
            return "There's nothing on your calendar to classify yet."
        lines = [
            f"I classified {len(result['events'])} events: "
            f"{counts.get('fixed', 0)} fixed, {counts.get('flexible', 0)} flexible"
            + (f", {counts.get('uncertain', 0)} uncertain" if counts.get("uncertain") else "")
            + "."
        ]
        flexible = [
            e for e in result["events"] if e.get("fixed_or_flexible") == "flexible"
        ]
        for event in flexible[:5]:
            lines.append(f"- {event.get('event_name')} (flexible)")
        uncertain = [
            e for e in result["events"] if e.get("fixed_or_flexible") == "uncertain"
        ]
        if uncertain:
            names = ", ".join(e.get("event_name", "?") for e in uncertain[:3])
            lines.append(f"I'm unsure about: {names}. Are those fixed or flexible?")
        return "\n".join(lines)

    def _format_classify_one(self, result: dict[str, Any]) -> str:
        if result.get("error"):
            return str(result["error"])
        event = result.get("event") or {}
        return (
            f"{event.get('event_name', 'That event')} is "
            f"{event.get('fixed_or_flexible')} ({event.get('event_type')}) — "
            f"{event.get('reason')}"
        )

    def _format_schedule_suggestion(self, result: dict[str, Any]) -> str:
        message = str(result.get("message") or "").strip()
        proposals = result.get("proposals") or []
        if not proposals:
            return message or "I couldn't find any flexible work to schedule."
        lines = [message or "Here's a suggested schedule:"]
        for block in proposals[:12]:
            title = block.get("task_title") or "Block"
            start = self._short_time(block.get("start_time"))
            end = self._short_time(block.get("end_time"))
            lines.append(f"- {title}: {start} to {end}")
        lines.append('Apply these? Say "yes" to add them, or "try again" for a different option.')
        return "\n".join(lines)

    def _format_preference_suggestion(
        self, result: dict[str, Any], pending: dict[str, Any]
    ) -> str:
        periods = pending.get("periods") or []
        label = self._join_periods(periods) if periods else "your preferred time"
        flexible = [
            e
            for e in (result.get("events") or [])
            if e.get("fixed_or_flexible") == "flexible"
        ]
        if not flexible:
            return (
                "I classified your calendar but didn't find any flexible tasks or "
                "events to schedule. Add a study block or task and I'll place it near "
                f"{label}."
            )
        lines = [
            f"Here are the flexible items I can schedule near {label}:"
        ]
        for event in flexible[:8]:
            lines.append(f"- {event.get('event_name')}")
        lines.append(
            "Want me to propose specific times near your preferred period and "
            "show them before changing anything?"
        )
        return "\n".join(lines)

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

        if not self._is_delete_request(message):
            return name, arguments

        title_queries = self._extract_delete_titles(message)
        if not title_queries:
            provided = str(
                arguments.get("title") or arguments.get("title_query") or ""
            ).strip()
            if provided and provided.lower() not in {"event", "events", "calendar"}:
                title_queries = [provided]
        delete_all = self._wants_delete_all(message)
        if not title_queries and not delete_all:
            return name, arguments
        delete_args: dict[str, Any] = {
            "title_query": title_queries[0] if title_queries else "event",
            "title_queries": title_queries,
            "delete_all_matches": delete_all,
        }
        date_range = self._delete_date_range(message)
        if date_range:
            delete_args["start_date"], delete_args["end_date"] = date_range
        return "delete_calendar_block", delete_args

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
        # The user gave a clock time but the router didn't resolve it (e.g. it
        # chatted via ai_agent, or asked AM/PM). Try to parse the new time from
        # the message against the matched block ("move gaming from 2pm to 7pm").
        if start_dt is None and self._message_has_clock_time(message):
            block = chat_agent_tools.resolve_single_block(
                chat_agent_tools.matching_study_blocks(title_query)
            )
            retimed = self._retime_block(message, block) if block else None
            if retimed:
                new_start, new_end = retimed
                return "move_calendar_block", {
                    "title_query": title_query,
                    "target_date": new_start.date().isoformat(),
                    "start_time": new_start.isoformat(),
                    "end_time": new_end.isoformat(),
                }
            # Couldn't parse it. Only the add/clarification paths will resolve the
            # time on a follow-up; for ai_agent etc. don't strand the request —
            # fall through to a day-only move if a day was named.
            if name in {"add_calendar_block", "propose_schedule_change", CLARIFICATION_ACTION}:
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

    # Spoken durations -> "<N> minutes/hours" so one numeric grammar covers all.
    _DURATION_WORDS = (
        (r"\ban?\s+hour\s+and\s+a\s+half\b", "90 minutes"),
        (r"\bhalf\s+an\s+hour\b", "30 minutes"),
        (r"\bhalf\s+hour\b", "30 minutes"),
        (r"\ba\s+couple\s+of\s+hours\b", "2 hours"),
        (r"\ba\s+couple\s+hours\b", "2 hours"),
        (r"\bquarter\s+of\s+an\s+hour\b", "15 minutes"),
        (r"\ban?\s+hour\b", "60 minutes"),
        (r"\ban?\s+minute\b", "1 minute"),
    )

    def _normalize_durations(self, text: str) -> str:
        for pattern, replacement in self._DURATION_WORDS:
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        return text

    def _unit_minutes(self, amount: str, unit: str) -> int | None:
        try:
            value = float(amount)
        except (TypeError, ValueError):
            return None
        minutes = int(round(value * 60 if unit.lower().startswith("h") else value))
        return minutes or None

    def _clean_title(self, raw: str) -> str:
        title = re.sub(r"^\s*(?:my|the|this|that|a|an)\s+", " ", raw, flags=re.IGNORECASE)
        return " ".join(title.strip(" .,:;!?-").split())

    def _parse_resize(self, text: str) -> tuple[str, str, int] | None:
        """Return (title, mode, minutes) for a resize phrase, or None.

        mode is "end_delta" (extend/shorten/end shift), "start_delta" (start
        earlier/later) or "absolute" (set the whole duration). ``minutes`` is
        signed for the delta modes.
        """

        unit = r"(hours?|hrs?|hr|h|minutes?|mins?|min|m)"
        num = r"(\d+(?:\.\d+)?)"

        # "make gaming start 30 minutes earlier" / "start gaming an hour later"
        for pattern, title_group, num_group, unit_group, dir_group in (
            (rf"\bmake\s+(?:my\s+|the\s+|this\s+)?(.+?)\s+start\s+{num}\s*{unit}\s+(earlier|sooner|later)\b", 1, 2, 3, 4),
            (rf"\b(?:start|begin)\s+(?:my\s+|the\s+|this\s+)?(.+?)\s+{num}\s*{unit}\s+(earlier|sooner|later)\b", 1, 2, 3, 4),
        ):
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                minutes = self._unit_minutes(match.group(num_group), match.group(unit_group))
                if minutes is None:
                    return None
                if match.group(dir_group).lower() in {"earlier", "sooner"}:
                    minutes = -minutes
                return self._clean_title(match.group(title_group)), "start_delta", minutes

        # "end gaming 30 minutes later" / "finish gaming an hour earlier"
        match = re.search(
            rf"\b(?:end|finish)\s+(?:my\s+|the\s+|this\s+)?(.+?)\s+{num}\s*{unit}\s+(earlier|sooner|later)\b",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            minutes = self._unit_minutes(match.group(2), match.group(3))
            if minutes is None:
                return None
            if match.group(4).lower() in {"earlier", "sooner"}:
                minutes = -minutes
            return self._clean_title(match.group(1)), "end_delta", minutes

        # "make gaming 30 minutes longer/shorter"
        match = re.search(
            rf"\bmake\s+(?:my\s+|the\s+|this\s+)?(.+?)\s+{num}\s*{unit}\s+(longer|shorter)\b",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            minutes = self._unit_minutes(match.group(2), match.group(3))
            if minutes is None:
                return None
            if match.group(4).lower() == "shorter":
                minutes = -minutes
            return self._clean_title(match.group(1)), "end_delta", minutes

        # "extend/shorten gaming by 30 minutes" (the original grammar)
        match = re.search(
            rf"\b(extend|lengthen|stretch|shorten|cut|reduce|trim)\b\s+"
            rf"(?:my\s+|the\s+|this\s+)?(.+?)\s+(?:by\s+)?{num}\s*{unit}\b",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            minutes = self._unit_minutes(match.group(3), match.group(4))
            if minutes is None:
                return None
            if match.group(1).lower() in {"shorten", "cut", "reduce", "trim"}:
                minutes = -minutes
            return self._clean_title(match.group(2)), "end_delta", minutes

        # Absolute duration: "set gaming to 2 hours" / "make gaming 90 minutes long".
        # Skip add-style phrasing ("make a study block for 2 hours") which means create.
        if not re.search(r"\b(?:for|new|create|add|schedule|set up|put)\b", text, flags=re.IGNORECASE):
            match = re.search(
                rf"\b(?:set|change|make)\s+(?:my\s+|the\s+|this\s+)?(.+?)\s+"
                rf"(?:to\s+be|into|to)?\s*{num}\s*{unit}\b(?:\s+long)?\s*$",
                text,
                flags=re.IGNORECASE,
            )
            if match:
                # group(1)=title, group(2)=number, group(3)=unit
                minutes = self._unit_minutes(match.group(2), match.group(3))
                if minutes is None or minutes <= 0:
                    return None
                return self._clean_title(match.group(1)), "absolute", minutes

        return None

    def _coerce_resize_intent(
        self,
        name: str,
        arguments: dict[str, Any],
        message: str,
    ) -> tuple[str, dict[str, Any]]:
        """Reroute resize phrasing to a move that changes the block's times.

        Covers "extend/shorten X by N", "make X N longer/shorter", "start X N
        earlier/later", and "set X to N hours" (absolute duration).
        """

        if name == "move_calendar_block":
            return name, arguments
        parsed = self._parse_resize(self._normalize_durations(message))
        if not parsed:
            return name, arguments
        title, mode, minutes = parsed
        if not title or title.lower() in self._NON_TITLE_WORDS:
            return name, arguments

        block = chat_agent_tools.resolve_single_block(
            chat_agent_tools.matching_study_blocks(title)
        )
        if block is None:
            return name, arguments
        cur_start = self._parse_naive_datetime(block.get("start_time"))
        cur_end = self._parse_naive_datetime(block.get("end_time"))
        if cur_start is None or cur_end is None:
            return name, arguments

        new_start, new_end = cur_start, cur_end
        if mode == "start_delta":
            new_start = cur_start + timedelta(minutes=minutes)
        elif mode == "absolute":
            new_end = cur_start + timedelta(minutes=minutes)
        else:  # end_delta
            new_end = cur_end + timedelta(minutes=minutes)
        if new_end <= new_start:
            return name, arguments
        return "move_calendar_block", {
            "title_query": title,
            "target_date": new_start.date().isoformat(),
            "start_time": new_start.isoformat(),
            "end_time": new_end.isoformat(),
        }

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

    _MONTHS = {
        "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
        "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
        "august": 8, "aug": 8, "september": 9, "sept": 9, "sep": 9,
        "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
    }

    def _move_target_date(self, message: str) -> date | None:
        """Resolve the day the user wants to move an event ONTO.

        Understands weekdays ("friday", "next monday"), today/tomorrow/tonight,
        ISO dates, calendar dates ("June 12", "the 12th", "12 June") and relative
        spans ("in 3 days", "in 2 weeks"). For "move X <source> to <target>" the
        target is the last date mentioned, so the match nearest the end wins.
        """

        lower = message.lower()
        today = effective_today()
        month_alt = "|".join(sorted(self._MONTHS, key=len, reverse=True))
        weekday_alt = "|".join(sorted(self._WEEKDAY_TOKENS, key=len, reverse=True))
        candidates: list[tuple[int, date]] = []

        def add(pos: int, day: date | None) -> None:
            if day is not None:
                candidates.append((pos, day))

        # ISO date (2026-06-12)
        for m in re.finditer(r"\b\d{4}-\d{2}-\d{2}\b", lower):
            add(m.start(), self._resolve_date_token(m.group(0)))
        # "June 12", "Jun 12th"
        for m in re.finditer(rf"\b({month_alt})\.?\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", lower):
            add(m.start(), self._month_day(m.group(1), int(m.group(2)), today))
        # "12 June", "12th of June"
        for m in re.finditer(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+(?:of\s+)?({month_alt})\b", lower):
            add(m.start(), self._month_day(m.group(2), int(m.group(1)), today))
        # "in 3 days", "in 2 weeks"
        for m in re.finditer(r"\bin\s+(\d{1,3})\s+(day|days|week|weeks)\b", lower):
            span = int(m.group(1)) * (7 if m.group(2).startswith("week") else 1)
            add(m.start(), today + timedelta(days=span))
        # "next/this <weekday>"
        for m in re.finditer(rf"\b(next|this)\s+({weekday_alt})\b", lower):
            add(m.start(), self._weekday_date(m.group(2), today, m.group(1)))
        # "next week" (no weekday) -> a week out
        for m in re.finditer(r"\bnext\s+week\b", lower):
            add(m.start(), today + timedelta(days=7))
        # "the 12th", "on the 3rd" — a day-of-month, not preceded by a month name
        for m in re.finditer(r"\bthe\s+(\d{1,2})(?:st|nd|rd|th)?\b|\b(\d{1,2})(?:st|nd|rd|th)\b", lower):
            before = lower[max(0, m.start() - 12):m.start()]
            if re.search(rf"(?:{month_alt})\.?\s*$", before):
                continue  # part of "June 12th" — already handled above
            add(m.start(), self._day_of_month(int(m.group(1) or m.group(2)), today))
        # plain weekday / today / tomorrow / tonight (skip if "next/this" prefixed)
        for m in re.finditer(rf"\b(today|tomorrow|tonight|{weekday_alt})\b", lower):
            before = lower[max(0, m.start() - 6):m.start()]
            if re.search(r"\b(?:next|this)\s+$", before):
                continue
            token = "today" if m.group(1) == "tonight" else m.group(1)
            add(m.start(), self._resolve_date_token(token))

        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[-1][1]

    def _month_day(self, month_token: str, day: int, today: date) -> date | None:
        month = self._MONTHS.get(month_token.lower())
        if not month:
            return None
        for year in (today.year, today.year + 1):
            try:
                candidate = date(year, month, day)
            except ValueError:
                return None
            if candidate >= today:
                return candidate
        return None

    def _day_of_month(self, day: int, today: date) -> date | None:
        year, month = today.year, today.month
        for _ in range(13):
            try:
                candidate = date(year, month, day)
            except ValueError:
                candidate = None
            if candidate is not None and candidate >= today:
                return candidate
            month += 1
            if month > 12:
                month, year = 1, year + 1
        return None

    def _weekday_date(self, weekday_token: str, today: date, qualifier: str) -> date | None:
        target = self._WEEKDAY_TOKENS.get(weekday_token.lower())
        if target is None:
            return None
        if qualifier.lower() == "next":
            # The named weekday in the following calendar week.
            next_monday = today - timedelta(days=today.weekday()) + timedelta(days=7)
            return next_monday + timedelta(days=target)
        return today + timedelta(days=(target - today.weekday()) % 7)

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
            # Resizing (extend/shorten/start earlier/set duration) is a move too —
            # accept all of those verbs so coerced resizes aren't second-guessed.
            if not self._has_any(
                lower,
                (
                    "move", "reschedule", "shift",
                    "extend", "lengthen", "stretch", "shorten", "cut", "reduce", "trim",
                    "make", "set", "change", "start", "begin", "end", "finish",
                    "longer", "shorter", "earlier", "sooner", "later",
                ),
            ):
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
        if name == "delete_calendar_block":
            if not self._is_delete_request(lower):
                return "Do you want me to remove an event from your calendar?"
            queries = arguments.get("title_queries")
            title_queries = queries if isinstance(queries, list) else []
            title_query = str(arguments.get("title_query") or "").strip().lower()
            delete_all = bool(arguments.get("delete_all_matches"))
            if not title_queries and title_query in {
                "",
                "event",
                "events",
                "calendar",
                "schedule",
            } and not delete_all:
                return (
                    "Which event should I remove? Tell me its name, date, or say "
                    "to remove all matching events."
                )
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
