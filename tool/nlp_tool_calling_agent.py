#!/usr/bin/env python3
"""Standalone NLP tool-calling router for Synctra.

This file is intentionally separate from the backend app. It turns a natural
language user request into one or more tool calls, then can optionally execute
those calls through the backend chat tools.

Examples:

    python tool/nlp_tool_calling_agent.py "what homework is due this week"
    python tool/nlp_tool_calling_agent.py "when am I free tomorrow"
    python tool/nlp_tool_calling_agent.py "schedule 2 hours for lab 7 by Friday"
    python tool/nlp_tool_calling_agent.py --model-dir /content/syntra_tool_router --confidence-test

Backend execution requires the backend dependencies and app context:

    python tool/nlp_tool_calling_agent.py --backend "what is on my calendar today"
"""

from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import os
import re
import sys
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib import request as urlrequest


ToolHandler = Callable[[dict[str, Any]], dict[str, Any] | Awaitable[dict[str, Any]]]
TOOL_LABEL_ORDER = [
    "get_assignments",
    "find_free_slots",
    "get_calendar_events",
    "get_tasks",
    "propose_schedule_change",
    "ai_agent",
]
TOOL_LABELS = set(TOOL_LABEL_ORDER)
CLARIFICATION_ACTION = "clarification"
ADD_CALENDAR_BLOCK_ACTION = "add_calendar_block"


@dataclass(frozen=True)
class ToolCall:
    """A planned tool call extracted from a user request."""

    name: str
    arguments: dict[str, Any]
    confidence: float
    reason: str


@dataclass(frozen=True)
class ConfidenceTestExample:
    """A labeled prompt used to inspect classifier confidence."""

    text: str
    label: str


class TrainedToolIntentModel:
    """Transformer classifier trained by tool/train_heavy_tool_router.py."""

    def __init__(self, model_dir: str | Path) -> None:
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError(
                "Install model dependencies first: "
                "pip install torch transformers"
            ) from exc

        self._torch = torch
        self.model_dir = Path(model_dir)
        self.tokenizer = AutoTokenizer.from_pretrained(self.model_dir)
        self.model = AutoModelForSequenceClassification.from_pretrained(self.model_dir)
        self.model.eval()

        labels_path = self.model_dir / "labels.json"
        if labels_path.exists():
            raw = json.loads(labels_path.read_text())
            labels = raw["labels"] if isinstance(raw, dict) else raw
            self.id_to_label = {idx: label for idx, label in enumerate(labels)}
        else:
            self.id_to_label = {
                int(idx): label for idx, label in self.model.config.id2label.items()
            }

    def predict(self, message: str) -> tuple[str, float]:
        encoded = self.tokenizer(
            message,
            return_tensors="pt",
            truncation=True,
            max_length=256,
        )
        with self._torch.no_grad():
            logits = self.model(**encoded).logits
            probs = self._torch.softmax(logits, dim=-1)[0]
            idx = int(self._torch.argmax(probs).item())
        label = self.id_to_label.get(idx, "ai_agent")
        return label, float(probs[idx].item())


class NlpToolCallingAgent:
    """Small deterministic NLP router for app tools.

    This is not a large language model. It is a lightweight intent model using
    keyword scoring plus date and duration extraction. It is useful as a safe
    first pass before an LLM, or as a fallback when the LLM does not call tools.
    """

    _ISO_DATE_RE = re.compile(r"\b(20\d{2}-\d{2}-\d{2})\b")
    _HOURS_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)\b")
    _MINUTES_RE = re.compile(r"\b(\d+)\s*(?:m|min|mins|minute|minutes)\b")
    _TIME_TEXT = r"\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?)?"
    _TIME_RANGE_RE = re.compile(
        rf"\b(?:from\s+)?({_TIME_TEXT})\s*(?:-|to|until|through)\s*({_TIME_TEXT})\b",
        re.IGNORECASE,
    )

    _WEEKDAYS = {
        "monday": 0,
        "mon": 0,
        "tuesday": 1,
        "tue": 1,
        "tues": 1,
        "wednesday": 2,
        "wed": 2,
        "thursday": 3,
        "thu": 3,
        "thur": 3,
        "thurs": 3,
        "friday": 4,
        "fri": 4,
        "saturday": 5,
        "sat": 5,
        "sunday": 6,
        "sun": 6,
    }

    _MONTHS = {
        "jan": 1,
        "january": 1,
        "feb": 2,
        "february": 2,
        "mar": 3,
        "march": 3,
        "apr": 4,
        "april": 4,
        "may": 5,
        "jun": 6,
        "june": 6,
        "jul": 7,
        "july": 7,
        "aug": 8,
        "august": 8,
        "sep": 9,
        "sept": 9,
        "september": 9,
        "oct": 10,
        "october": 10,
        "nov": 11,
        "november": 11,
        "dec": 12,
        "december": 12,
    }

    _MONTH_DAY_RE = re.compile(
        r"\b("
        r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|"
        r"jul(?:y)?|aug(?:ust)?|sep(?:t|tember)?|oct(?:ober)?|"
        r"nov(?:ember)?|dec(?:ember)?"
        r")\s+(\d{1,2})(?:st|nd|rd|th)?(?:,\s*(20\d{2}))?\b",
        re.IGNORECASE,
    )

    def __init__(
        self,
        *,
        today: date | None = None,
        model_dir: str | Path | None = None,
        confidence_threshold: float = 0.8,
    ) -> None:
        self.today = today or date.today()
        self.confidence_threshold = confidence_threshold
        self.intent_model: TrainedToolIntentModel | None = None
        if model_dir:
            path = Path(model_dir)
            if path.exists():
                self.intent_model = TrainedToolIntentModel(path)

    def plan(
        self,
        message: str,
        *,
        clarification_pending: bool = False,
    ) -> list[ToolCall]:
        """Return the tool calls that best match [message]."""

        text = " ".join(message.strip().split())
        lower = text.lower()
        if not lower:
            return []

        start, end, date_reason = self._date_range(lower)
        calendar_block_call = self._calendar_block_call_or_clarification(
            text=text,
            lower=lower,
            date_value=start,
        )
        if calendar_block_call is not None:
            return [calendar_block_call]
        calls: list[ToolCall] = []

        if self.intent_model is not None:
            label, confidence = self.intent_model.predict(text)
            override_label = self._high_precision_label(lower)
            if override_label:
                return [
                    self._call_for_label(
                        override_label,
                        text=text,
                        lower=lower,
                        start=start,
                        end=end,
                        confidence=0.95,
                        reason=(
                            f"High-precision routing rule selected {override_label}; "
                            f"transformer predicted {label} at {confidence:.2f}."
                        ),
                    )
                ]
            if label in TOOL_LABELS and confidence >= self.confidence_threshold:
                return [
                    self._call_for_label(
                        label,
                        text=text,
                        lower=lower,
                        start=start,
                        end=end,
                        confidence=confidence,
                        reason=f"Transformer intent model selected {label}.",
                    )
                ]
            if clarification_pending:
                return [
                    self._ai_agent_call(
                        text,
                        confidence=confidence,
                        reason=(
                            "Classifier confidence stayed below "
                            f"{self.confidence_threshold:.2f} after clarification; "
                            "falling back to ai_agent."
                        ),
                    )
                ]
            return [
                self._clarification_call(
                    text,
                    predicted_label=label,
                    confidence=confidence,
                    reason=(
                        "Classifier confidence "
                        f"{confidence:.2f} is below {self.confidence_threshold:.2f}; "
                        "ask a clarification before calling a tool."
                    ),
                )
            ]

        if self._wants_schedule_proposal(lower):
            task_name = self._extract_task_name(text)
            estimated_minutes = self._extract_minutes(lower)
            hours = max(0.25, round(estimated_minutes / 60.0, 2))
            calls.append(
                ToolCall(
                    name="propose_schedule_change",
                    arguments={
                        "task_name": task_name,
                        "hours": hours,
                        "deadline": self._deadline_iso(lower, end),
                        "estimated_minutes": estimated_minutes,
                    },
                    confidence=0.91,
                    reason="User is asking to schedule or plan study/work time.",
                )
            )
            return calls

        if self._wants_free_slots(lower):
            calls.append(
                ToolCall(
                    name="find_free_slots",
                    arguments={
                        "start_date": start.isoformat(),
                        "end_date": end.isoformat(),
                    },
                    confidence=0.9,
                    reason=f"User is asking for open/free time; {date_reason}.",
                )
            )

        if self._wants_calendar(lower):
            calls.append(
                ToolCall(
                    name="get_calendar_events",
                    arguments={
                        "start_date": start.isoformat(),
                        "end_date": end.isoformat(),
                    },
                    confidence=0.86,
                    reason=f"User is asking about calendar/classes/events; {date_reason}.",
                )
            )

        if self._wants_tasks(lower):
            calls.append(
                ToolCall(
                    name="get_tasks",
                    arguments={
                        "due_start": start.isoformat(),
                        "due_end": end.isoformat(),
                    },
                    confidence=0.87,
                    reason=f"User is asking about tasks/homework/deadlines; {date_reason}.",
                )
            )

            if self._wants_live_canvas(lower):
                calls.append(
                    ToolCall(
                        name="get_assignments",
                        arguments={},
                        confidence=0.82,
                        reason="User mentioned Canvas or live assignments.",
                    )
                )

        if not calls:
            return [
                self._ai_agent_call(
                    text,
                    confidence=0.4,
                    reason="No matching Syntra tool intent was found.",
                )
            ]

        return self._dedupe_calls(calls)

    def _high_precision_label(self, text: str) -> str | None:
        """Prefer explicit intent phrases over an overconfident classifier."""

        if self._explicit_schedule_request(text):
            return "propose_schedule_change"
        if self._explicit_ai_agent_request(text):
            return "ai_agent"
        if self._explicit_assignment_sync_request(text):
            return "get_assignments"
        if self._explicit_free_slot_request(text):
            return "find_free_slots"
        if self._explicit_calendar_request(text):
            return "get_calendar_events"
        if self._explicit_task_request(text):
            return "get_tasks"
        return None

    def _explicit_schedule_request(self, text: str) -> bool:
        if any(
            phrase in text
            for phrase in (
                "find time and schedule",
                "schedule ",
                "plan ",
                "add a study block",
                "add time",
                "block time",
                "reserve time",
                "create calendar time",
                "put study time",
                "put homework time",
                "make time to finish",
                "make time for",
            )
        ):
            return self._wants_schedule_proposal(text)
        return False

    def _explicit_ai_agent_request(self, text: str) -> bool:
        if re.fullmatch(
            r"(hi|hello|hey|thanks|thank you|ok|okay|yes|no|sure|maybe|good morning|good afternoon|good evening)[.!?]*",
            text,
        ):
            return True
        if any(
            phrase in text
            for phrase in (
                "i feel stressed",
                "i'm stressed",
                "i am stressed",
                "feeling stressed",
                "i feel overwhelmed",
                "i'm overwhelmed",
                "i am overwhelmed",
                "feeling overwhelmed",
                "i feel anxious",
                "i'm anxious",
                "i am anxious",
                "feeling anxious",
                "i feel tired",
                "i'm tired",
                "i am tired",
                "i need a break",
                "i need encouragement",
                "i need motivation",
            )
        ):
            return True
        if any(
            phrase in text
            for phrase in (
                "write ",
                "rewrite ",
                "draft ",
                "explain ",
                "summarize ",
                "brainstorm ",
                "proofread ",
                "translate ",
                "convert ",
                "make a checklist",
                "make this sentence",
                "make my paragraph",
                "give me ideas",
                "give me tips",
                "help me debug",
                "help me understand",
                "help me outline",
                "what should i say",
                "how should i ask",
                "how do i ask",
            )
        ):
            return True
        if text.startswith(("can you ", "please ", "i need help with this: ")):
            return not any(
                tool_phrase in text
                for tool_phrase in (
                    "schedule",
                    "calendar",
                    "free time",
                    "free slots",
                    "open time",
                    "canvas",
                    "course portal",
                    "homework due",
                    "assignments due",
                    "deadline",
                )
            )
        return False

    def _explicit_assignment_sync_request(self, text: str) -> bool:
        if any(
            source in text
            for source in (
                "canvas",
                "lms",
                "course site",
                "course portal",
                "course website",
                "learning system",
                "portal",
            )
        ):
            return any(
                word in text
                for word in (
                    "assignment",
                    "assignments",
                    "homework",
                    "deadline",
                    "deadlines",
                    "posted",
                    "new work",
                    "course work",
                    "anything new",
                    "sync",
                    "refresh",
                    "pull",
                    "load",
                )
            )
        return bool(
            re.search(
                r"\b(?:see whether|check if|did)\b.+\b(?:posted|post|add|added)\b.+\b(?:new work|work|assignment|homework|task|anything new)\b",
                text,
            )
        )

    def _explicit_free_slot_request(self, text: str) -> bool:
        if any(
            phrase in text
            for phrase in (
                "free slot",
                "free slots",
                "free time",
                "open slot",
                "open slots",
                "open time",
                "availability",
                "available",
                "room in my schedule",
                "space in my schedule",
                "gap in my calendar",
                "when am i free",
                "when can i",
            )
        ):
            return True
        if re.search(
            r"\bfind\s+\d+(?:\.\d+)?\s*(?:h|hr|hrs|hour|hours|m|min|mins|minute|minutes)\s+(?:for|to)\s+(?:studying|study|homework|work)\b",
            text,
        ):
            return True
        if re.search(
            r"\bfind\s+(?:one|two|three)\s+(?:hours?|minutes?)\s+(?:for|to)\s+(?:studying|study|homework|work)\b",
            text,
        ):
            return True
        return False

    def _explicit_calendar_request(self, text: str) -> bool:
        event_words = (
            "class",
            "classes",
            "lecture",
            "lectures",
            "lab",
            "discussion",
            "section",
            "exam review",
            "office hours",
            "meeting",
            "meetings",
            "appointment",
            "appointments",
            "event",
            "events",
        )
        if "due" in text or "deadline" in text or "homework" in text:
            return False
        if "my calendar" in text or "on my calendar" in text:
            return True
        if any(
            phrase in text
            for phrase in (
                "what classes",
                "what class",
                "show calendar",
                "show my calendar",
                "calendar events",
                "what time is",
                "when is my",
                "when is ",
            )
        ):
            return any(word in text for word in event_words)
        if "do i have" in text or "is there a" in text:
            return any(word in text for word in event_words)
        return False

    def _explicit_task_request(self, text: str) -> bool:
        return any(
            phrase in text
            for phrase in (
                "tell me my homework",
                "what homework",
                "what assignments are due",
                "what do i need to turn in",
                "what do i need to submit",
                "need to submit",
                "need to turn in",
                "homework for",
                "upcoming due dates",
                "next homework deadline",
                "assignment deadline",
                "pending submissions",
            )
        )

    def _clarification_call(
        self,
        message: str,
        *,
        predicted_label: str,
        confidence: float,
        reason: str,
    ) -> ToolCall:
        question, options = self._clarification_question(message, predicted_label)
        return ToolCall(
            name=CLARIFICATION_ACTION,
            arguments={
                "message": message,
                "question": question,
                "options": options,
                "predicted_tool": predicted_label,
                "next_step": (
                    "Ask this question first. If the next user reply is still "
                    "below the confidence threshold, route to ai_agent."
                ),
            },
            confidence=confidence,
            reason=reason,
        )

    def _calendar_block_call_or_clarification(
        self,
        *,
        text: str,
        lower: str,
        date_value: date,
    ) -> ToolCall | None:
        if not self._wants_calendar_block_creation(lower):
            return None

        title = self._extract_calendar_block_title(text)
        time_range = self._extract_time_range(lower)
        has_date = self._has_explicit_date_text(lower)

        missing: list[str] = []
        if not title:
            missing.append("event name")
        if not has_date:
            missing.append("date")
        if time_range is None:
            missing.append("start and end time")

        if missing:
            missing_text = ", ".join(missing)
            return ToolCall(
                name=CLARIFICATION_ACTION,
                arguments={
                    "message": text,
                    "question": (
                        f"What {missing_text} should I use for this calendar block? "
                        "For example: Study for math tomorrow from 2 PM to 3 PM."
                    ),
                    "options": [ADD_CALENDAR_BLOCK_ACTION, "ai_agent"],
                    "predicted_tool": ADD_CALENDAR_BLOCK_ACTION,
                    "next_step": (
                        "Ask for the missing calendar block details before adding a block."
                    ),
                },
                confidence=0.94,
                reason="Calendar block creation is missing required details.",
            )

        start_time, end_time = time_range
        start_dt = datetime.combine(date_value, start_time)
        end_dt = datetime.combine(date_value, end_time)
        if end_dt <= start_dt:
            end_dt += timedelta(days=1)

        return ToolCall(
            name=ADD_CALENDAR_BLOCK_ACTION,
            arguments={
                "title": title,
                "start_time": start_dt.isoformat(),
                "end_time": end_dt.isoformat(),
            },
            confidence=0.95,
            reason="User provided a calendar block title, date, and time range.",
        )

    def _wants_calendar_block_creation(self, text: str) -> bool:
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

    def _has_explicit_date_text(self, text: str) -> bool:
        if self._ISO_DATE_RE.search(text) or self._MONTH_DAY_RE.search(text):
            return True
        if any(word in text for word in ("today", "tomorrow", "weekend")):
            return True
        tokens = set(re.findall(r"\b[a-z]+\b", text.lower()))
        return any(token in tokens for token in self._WEEKDAYS)

    def _extract_time_range(self, text: str) -> tuple[Any, Any] | None:
        match = self._TIME_RANGE_RE.search(text)
        if not match:
            return None
        start_raw, end_raw = match.groups()
        end_ampm = self._time_ampm(end_raw)
        start_time = self._parse_time_token(start_raw, default_ampm=end_ampm)
        end_time = self._parse_time_token(end_raw)
        if start_time is None or end_time is None:
            return None
        return start_time, end_time

    def _time_ampm(self, raw: str) -> str | None:
        match = re.search(r"(a\.?m\.?|p\.?m\.?)", raw, flags=re.IGNORECASE)
        if not match:
            return None
        value = match.group(1).lower().replace(".", "")
        return "am" if value.startswith("a") else "pm"

    def _parse_time_token(self, raw: str, *, default_ampm: str | None = None) -> Any | None:
        from datetime import time

        match = re.search(
            r"\b(\d{1,2})(?::(\d{2}))?\s*(a\.?m\.?|p\.?m\.?)?\b",
            raw,
            flags=re.IGNORECASE,
        )
        if not match:
            return None
        hour = int(match.group(1))
        minute = int(match.group(2) or "0")
        ampm = self._time_ampm(match.group(3) or "") or default_ampm
        if minute > 59:
            return None
        if ampm:
            if hour < 1 or hour > 12:
                return None
            if ampm == "pm" and hour != 12:
                hour += 12
            if ampm == "am" and hour == 12:
                hour = 0
        elif hour > 23:
            return None
        elif hour < 13:
            return None
        return time(hour, minute)

    def _extract_calendar_block_title(self, text: str) -> str:
        cleaned = self._TIME_RANGE_RE.sub(" ", text)
        cleaned = self._ISO_DATE_RE.sub(" ", cleaned)
        cleaned = self._MONTH_DAY_RE.sub(" ", cleaned)
        cleaned = re.sub(
            r"\b(?:today|tomorrow|monday|mon|tuesday|tue|wednesday|wed|"
            r"thursday|thu|friday|fri|saturday|sat|sunday|sun|weekend)\b",
            " ",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"^\s*(?:please\s+)?(?:add|create|put)\s+(?:a\s+)?"
            r"(?:(?:calendar|study)\s+)?block"
            r"(?:\s*(?:to|in|on)?\s*(?:my\s+)?calendar)?\s*",
            " ",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            r"^\s*(?:called|named|for)\s+",
            " ",
            cleaned,
            flags=re.IGNORECASE,
        )
        title = " ".join(cleaned.strip(" .,:;-").split())
        if title.lower() in {"calendar", "block", "calendar block", "event"}:
            return ""
        return title[:120]

    def _clarification_question(
        self,
        message: str,
        predicted_label: str,
    ) -> tuple[str, list[str]]:
        lower = message.lower()
        if self._wants_free_slots(lower) and self._wants_schedule_proposal(lower):
            return (
                "Do you want me to find free time, or schedule a study block?",
                ["find_free_slots", "propose_schedule_change"],
            )
        if self._wants_free_slots(lower) and self._wants_calendar(lower):
            return (
                "Do you want to see what is already on your calendar, or find open time?",
                ["get_calendar_events", "find_free_slots"],
            )
        if self._wants_live_canvas(lower) and self._wants_tasks(lower):
            return (
                "Do you want me to sync live Canvas assignments, or show your current task list?",
                ["get_assignments", "get_tasks"],
            )
        if predicted_label == "find_free_slots":
            return (
                "Do you want me to find free time on your calendar?",
                ["find_free_slots", "ai_agent"],
            )
        if predicted_label == "get_calendar_events":
            return (
                "Do you want me to show calendar events and classes?",
                ["get_calendar_events", "ai_agent"],
            )
        if predicted_label == "get_tasks":
            return (
                "Do you want me to show tasks, homework, and deadlines?",
                ["get_tasks", "ai_agent"],
            )
        if predicted_label == "get_assignments":
            return (
                "Do you want me to check Canvas or your course site for assignments?",
                ["get_assignments", "ai_agent"],
            )
        if predicted_label == "propose_schedule_change":
            return (
                "Do you want me to schedule a study or work block?",
                ["propose_schedule_change", "ai_agent"],
            )
        return (
            "Do you want me to use a Syntra tool, or should I answer generally?",
            [
                "get_assignments",
                "find_free_slots",
                "get_calendar_events",
                "get_tasks",
                "propose_schedule_change",
                "ai_agent",
            ],
        )

    def _call_for_label(
        self,
        label: str,
        *,
        text: str,
        lower: str,
        start: date,
        end: date,
        confidence: float,
        reason: str,
    ) -> ToolCall:
        if label == "propose_schedule_change":
            estimated_minutes = self._extract_minutes(lower)
            return ToolCall(
                name=label,
                arguments={
                    "task_name": self._extract_task_name(text),
                    "hours": max(0.25, round(estimated_minutes / 60.0, 2)),
                    "deadline": self._deadline_iso(lower, end),
                    "estimated_minutes": estimated_minutes,
                },
                confidence=confidence,
                reason=reason,
            )
        if label == "find_free_slots":
            return ToolCall(
                name=label,
                arguments={"start_date": start.isoformat(), "end_date": end.isoformat()},
                confidence=confidence,
                reason=reason,
            )
        if label == "get_calendar_events":
            return ToolCall(
                name=label,
                arguments={"start_date": start.isoformat(), "end_date": end.isoformat()},
                confidence=confidence,
                reason=reason,
            )
        if label == "get_tasks":
            return ToolCall(
                name=label,
                arguments={"due_start": start.isoformat(), "due_end": end.isoformat()},
                confidence=confidence,
                reason=reason,
            )
        if label == "get_assignments":
            return ToolCall(name=label, arguments={}, confidence=confidence, reason=reason)
        return self._ai_agent_call(text, confidence=confidence, reason=reason)

    def _ai_agent_call(self, message: str, *, confidence: float, reason: str) -> ToolCall:
        return ToolCall(
            name="ai_agent",
            arguments={"message": message},
            confidence=confidence,
            reason=reason,
        )

    async def run(
        self,
        message: str,
        registry: dict[str, ToolHandler],
        *,
        clarification_pending: bool = False,
    ) -> list[dict[str, Any]]:
        """Plan and execute tool calls using [registry]."""

        results: list[dict[str, Any]] = []
        for call in self.plan(message, clarification_pending=clarification_pending):
            if call.name == CLARIFICATION_ACTION:
                results.append(
                    {
                        "tool_call": asdict(call),
                        "result": {
                            "needs_clarification": True,
                            "question": call.arguments["question"],
                            "options": call.arguments["options"],
                        },
                    }
                )
                continue
            handler = registry.get(call.name)
            if handler is None:
                results.append(
                    {
                        "tool_call": asdict(call),
                        "result": {"error": f"No handler registered for {call.name}"},
                    }
                )
                continue

            value = handler(call.arguments)
            if inspect.isawaitable(value):
                value = await value
            results.append({"tool_call": asdict(call), "result": value})
        return results

    def _wants_schedule_proposal(self, text: str) -> bool:
        if any(
            phrase in text
            for phrase in (
                "plan this week",
                "plan my week",
                "plan the week",
                "help me plan this week",
                "help me plan my week",
                "help me plan the week",
                "set up a plan for this week",
                "make a plan for this week",
            )
        ):
            return True
        has_plan_word = any(
            word in text
            for word in (
                "schedule",
                "plan",
                "study block",
                "study time",
                "work on",
                "make time",
                "add time",
            )
        )
        has_work_word = any(
            word in text
            for word in (
                "homework",
                "assignment",
                "task",
                "exam",
                "quiz",
                "lab",
                "project",
                "study",
            )
        )
        asking_schedule_view = any(
            phrase in text
            for phrase in (
                "my schedule",
                "class schedule",
                "what is on my schedule",
                "what's on my schedule",
            )
        )
        return has_plan_word and has_work_word and not asking_schedule_view

    def _wants_free_slots(self, text: str) -> bool:
        return any(
            phrase in text
            for phrase in (
                "free time",
                "open time",
                "available",
                "availability",
                "free slot",
                "free slots",
                "when am i free",
                "when can i",
            )
        )

    def _wants_calendar(self, text: str) -> bool:
        return any(
            word in text
            for word in (
                "calendar",
                "class",
                "classes",
                "event",
                "events",
                "meeting",
                "lecture",
                "lectures",
                "section",
                "schedule today",
                "my schedule",
            )
        )

    def _wants_tasks(self, text: str) -> bool:
        return any(
            word in text
            for word in (
                "task",
                "tasks",
                "homework",
                "hw",
                "assignment",
                "assignments",
                "due",
                "deadline",
                "quiz",
                "exam",
                "project",
                "lab",
                "todo",
                "to do",
            )
        )

    def _wants_live_canvas(self, text: str) -> bool:
        return "canvas" in text or "live assignment" in text or "sync assignment" in text

    def _date_range(self, text: str) -> tuple[date, date, str]:
        iso_dates = [datetime.strptime(v, "%Y-%m-%d").date() for v in self._ISO_DATE_RE.findall(text)]
        if len(iso_dates) >= 2:
            start, end = sorted(iso_dates[:2])
            return start, end, f"using explicit dates {start} to {end}"
        if len(iso_dates) == 1:
            d = iso_dates[0]
            return d, d, f"using explicit date {d}"

        month_day = self._month_day_date(text)
        if month_day is not None:
            return month_day, month_day, f"using date {month_day}"

        if "tomorrow" in text:
            d = self.today + timedelta(days=1)
            return d, d, "using tomorrow"
        if "today" in text:
            return self.today, self.today, "using today"
        if "next week" in text:
            monday = self._monday(self.today) + timedelta(days=7)
            friday = monday + timedelta(days=4)
            return monday, friday, "using next school week"
        if "this week" in text or "week" in text:
            monday = self._monday(self.today)
            friday = monday + timedelta(days=4)
            return monday, friday, "using this school week"
        if "weekend" in text:
            saturday = self._monday(self.today) + timedelta(days=5)
            sunday = saturday + timedelta(days=1)
            return saturday, sunday, "using this weekend"

        weekday = self._weekday_date(text)
        if weekday is not None:
            return weekday, weekday, f"using {weekday.isoformat()}"

        monday = self._monday(self.today)
        friday = monday + timedelta(days=4)
        return monday, friday, "defaulting to this school week"

    def _weekday_date(self, text: str) -> date | None:
        tokens = set(re.findall(r"\b[a-z]+\b", text.lower()))
        for token, target in self._WEEKDAYS.items():
            if token not in tokens:
                continue
            delta = (target - self.today.weekday()) % 7
            if "next" in tokens and delta == 0:
                delta = 7
            return self.today + timedelta(days=delta)
        return None

    def _month_day_date(self, text: str) -> date | None:
        match = self._MONTH_DAY_RE.search(text)
        if not match:
            return None
        month_text, day_text, year_text = match.groups()
        month = self._MONTHS[month_text[:3].lower()]
        day = int(day_text)
        year = int(year_text) if year_text else self.today.year
        try:
            parsed = date(year, month, day)
        except ValueError:
            return None
        if year_text is None and parsed < self.today - timedelta(days=30):
            parsed = date(year + 1, month, day)
        return parsed

    def _deadline_iso(self, text: str, fallback: date) -> str:
        if "by " in text or "due " in text or "deadline" in text:
            return f"{fallback.isoformat()}T23:59:00"
        return f"{fallback.isoformat()}T23:59:00"

    def _extract_minutes(self, text: str) -> int:
        hours = self._HOURS_RE.search(text)
        if hours:
            return max(15, int(round(float(hours.group(1)) * 60)))
        minutes = self._MINUTES_RE.search(text)
        if minutes:
            return max(15, int(minutes.group(1)))
        return 60

    def _extract_task_name(self, text: str) -> str:
        cleaned = re.sub(self._HOURS_RE, "", text)
        cleaned = re.sub(self._MINUTES_RE, "", cleaned)
        patterns = [
            r"\b(?:for|on|work on|study for)\s+(.+?)(?:\s+by\s+|\s+due\s+|$)",
            r"\b(?:schedule|plan)\s+(.+?)(?:\s+by\s+|\s+due\s+|$)",
        ]
        for pattern in patterns:
            match = re.search(pattern, cleaned, flags=re.IGNORECASE)
            if match:
                title = match.group(1).strip(" .,:;-")
                if title:
                    return title[:120]
        return "Study block"

    def _dedupe_calls(self, calls: list[ToolCall]) -> list[ToolCall]:
        seen: set[str] = set()
        unique: list[ToolCall] = []
        for call in sorted(calls, key=lambda c: c.confidence, reverse=True):
            if call.name in seen:
                continue
            seen.add(call.name)
            unique.append(call)
        return unique

    @staticmethod
    def _monday(day: date) -> date:
        return day - timedelta(days=day.weekday())


def mock_registry() -> dict[str, ToolHandler]:
    """Simple handlers for checking routing without backend setup."""

    def reply(name: str) -> ToolHandler:
        def handler(args: dict[str, Any]) -> dict[str, Any]:
            return {"mock": True, "tool": name, "arguments_received": args}

        return handler

    return {
        "get_assignments": reply("get_assignments"),
        "get_tasks": reply("get_tasks"),
        "get_calendar_events": reply("get_calendar_events"),
        "find_free_slots": reply("find_free_slots"),
        "propose_schedule_change": reply("propose_schedule_change"),
        "ai_agent": reply("ai_agent"),
    }


def backend_registry() -> dict[str, ToolHandler]:
    """Bridge to backend/app/services/chat_agent_common.py."""

    repo_root = Path(__file__).resolve().parents[1]
    backend_dir = repo_root / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))

    from app.services.chat_agent_common import execute_tool

    def make_handler(tool_name: str) -> ToolHandler:
        async def handler(args: dict[str, Any]) -> dict[str, Any]:
            return await execute_tool(tool_name, args)

        return handler

    return {
        "get_assignments": make_handler("get_assignments"),
        "get_tasks": make_handler("get_tasks"),
        "get_calendar_events": make_handler("get_calendar_events"),
        "find_free_slots": make_handler("find_free_slots"),
        "propose_schedule_change": make_handler("propose_schedule_change"),
    }


def colab_ai_agent_handler(
    host: str | None = None,
    *,
    model: str | None = None,
    timeout_s: float = 120,
) -> ToolHandler:
    """Fallback handler that sends ai_agent requests to Colab /api/generate."""

    resolved_host = (
        host
        or os.getenv("COLAB_AI_AGENT_HOST")
        or os.getenv("COLAB_COURSE_IMPORT_HOST")
        or os.getenv("COLAB_LLM_HOST")
        or os.getenv("OLLAMA_HOST")
        or ""
    ).rstrip("/")
    resolved_model = (
        model
        or os.getenv("COLAB_COURSE_MODEL")
        or os.getenv("OLLAMA_MODEL")
        or "Qwen/Qwen2.5-3B-Instruct"
    )

    def handler(args: dict[str, Any]) -> dict[str, Any]:
        message = str(args.get("message") or "").strip()
        if not resolved_host:
            return {
                "error": (
                    "No Colab host configured. Set OLLAMA_HOST, "
                    "COLAB_AI_AGENT_HOST, or COLAB_COURSE_IMPORT_HOST to the "
                    "tunnel URL printed by colab_course_import_agent_server.py."
                ),
                "message": message,
            }
        payload = {
            "model": resolved_model,
            "prompt": message,
            "stream": False,
            "options": {"temperature": 0, "syntra_mode": "ai_agent"},
        }
        req = urlrequest.Request(
            f"{resolved_host}/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "ngrok-skip-browser-warning": "true",
            },
            method="POST",
        )
        try:
            with urlrequest.urlopen(req, timeout=timeout_s) as response:
                data = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            return {"error": f"Colab AI request failed: {exc}", "message": message}

        content = data.get("response") if isinstance(data, dict) else None
        return {
            "assistant_message": content or "",
            "raw": data,
        }

    return handler


def _json_default(value: Any) -> str:
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return str(value)


def _strip_notebook_args(argv: list[str]) -> list[str]:
    """Remove Jupyter/Colab kernel args before argparse sees positionals."""

    cleaned: list[str] = []
    skip_next = False
    for arg in argv:
        if skip_next:
            skip_next = False
            continue
        if arg == "-f":
            skip_next = True
            continue
        if arg.startswith("-f="):
            continue
        cleaned.append(arg)
    return cleaned


def confidence_test_examples() -> list[ConfidenceTestExample]:
    """Return 1000 balanced prompts for confidence testing."""

    target_counts = {
        "get_assignments": 167,
        "find_free_slots": 167,
        "get_calendar_events": 167,
        "get_tasks": 167,
        "propose_schedule_change": 166,
        "ai_agent": 166,
    }
    courses = [
        "calculus",
        "biology",
        "chemistry",
        "computer science",
        "history",
        "english",
        "physics",
        "statistics",
        "algorithms",
        "economics",
        "psychology",
        "art history",
    ]
    work_items = [
        "homework 1",
        "lab 3",
        "quiz 2",
        "project proposal",
        "midterm review",
        "essay draft",
        "problem set",
        "reading notes",
        "final exam",
        "discussion post",
        "lab report",
        "worksheet",
    ]
    days = [
        "today",
        "tomorrow",
        "Friday",
        "this week",
        "next week",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
    ]
    durations = ["30 minutes", "45 minutes", "1 hour", "90 minutes", "2 hours", "3 hours"]
    event_types = ["lecture", "lab", "discussion", "section", "exam review", "office hours"]
    ai_topics = [
        "write an email to my professor",
        "explain recursion",
        "summarize these notes",
        "rewrite this paragraph",
        "brainstorm topics for my history essay",
        "explain big O notation",
        "make this sentence more professional",
        "draft an apology email",
        "help me understand this error",
        "give me study tips for algorithms",
        "translate this sentence into Spanish",
        "outline my paper",
        "explain photosynthesis",
        "help me choose a capstone topic",
        "proofread my message",
        "explain this syllabus policy",
        "make a checklist for finals",
        "write a polite reply to my teammate",
        "help me debug my Python code",
        "convert this paragraph into bullet points",
        "write a thesis statement for my essay",
        "make an outline for my research paper",
        "explain this assignment prompt",
        "give me topic ideas for my presentation",
        "help me make my paragraph clearer",
        "draft a message asking for an extension",
        "summarize this textbook section",
        "explain the difference between mitosis and meiosis",
        "turn these notes into study questions",
        "write a professional response to my group",
        "explain this grading policy",
        "help me prepare talking points",
        "make this email sound polite",
        "give me thesis statement ideas",
        "help me understand my SQL error",
        "rewrite this sentence in a formal tone",
        "brainstorm arguments for my paper",
        "explain this concept like I am new",
        "create a study checklist for my exam",
        "help me choose a research topic",
    ]

    pools: dict[str, list[ConfidenceTestExample]] = {
        label: [] for label in TOOL_LABEL_ORDER
    }
    seen: set[tuple[str, str]] = set()

    def add(label: str, text: str) -> None:
        key = (label, " ".join(text.lower().split()))
        if key in seen:
            return
        seen.add(key)
        pools[label].append(ConfidenceTestExample(text=text, label=label))

    assignment_templates = [
        "see whether {course} posted new work",
        "check canvas for {course} assignments",
        "pull {course} homework from canvas",
        "refresh {course} assignment feed from the LMS",
        "load new {course} course work from the portal",
        "sync {course} deadlines from the course website",
        "did {course} add anything new on canvas",
        "check if {course} posted a new assignment",
    ]
    for course in courses:
        for template in assignment_templates:
            add("get_assignments", template.format(course=course))

    assignment_item_templates = [
        "load {item} details from canvas",
        "sync the {item} from my course portal",
        "check whether the LMS has a {item}",
        "fetch the posted {item} instructions",
        "pull the {item} assignment from canvas",
        "refresh course site details for {item}",
        "download the newest {item} from my online class",
        "check if my course website posted the {item}",
    ]
    for item in work_items:
        for template in assignment_item_templates:
            add("get_assignments", template.format(item=item))

    free_templates = [
        "when am I free {day}",
        "find free time {day}",
        "show open slots {day}",
        "find a free block {day}",
        "what free slots do I have {day}",
        "do I have open time {day}",
        "find {duration} for studying {day}",
        "when can I work on homework {day}",
        "is there room in my schedule {day}",
        "show availability after class {day}",
    ]
    for idx, day in enumerate(days):
        for template in free_templates:
            add(
                "find_free_slots",
                template.format(day=day, duration=durations[idx % len(durations)]),
            )

    course_free_templates = [
        "where do I have open time for {course} {day}",
        "can I fit in {course} studying {day}",
        "show my available time for {course} {day}",
        "find a gap for {course} work {day}",
        "when can I work on {course} homework {day}",
        "find an open block for {course} {day}",
    ]
    for course in courses:
        for day in days:
            for template in course_free_templates:
                add("find_free_slots", template.format(course=course, day=day))

    calendar_templates = [
        "when is my {course} {event_type} {day}",
        "do I have {course} {event_type} {day}",
        "show my {course} calendar {day}",
        "what time is {course} on my calendar {day}",
        "list my {course} meetings {day}",
        "what classes do I have {day}",
        "show calendar events for {day}",
    ]
    for course in courses:
        for idx, day in enumerate(days):
            event_type = event_types[idx % len(event_types)]
            for template in calendar_templates:
                add(
                    "get_calendar_events",
                    template.format(course=course, event_type=event_type, day=day),
                )

    task_templates = [
        "what {item} is due {day}",
        "show deadline for {item} {day}",
        "do I need to submit {item} {day}",
        "tell me my homework for {day}",
        "what assignments are due {day}",
        "show tasks for {day}",
        "what do I need to turn in {day}",
        "show upcoming due dates for {item}",
    ]
    for item in work_items:
        for day in days:
            for template in task_templates:
                add("get_tasks", template.format(item=item, day=day))

    schedule_templates = [
        "schedule {duration} for {item} by {day}",
        "plan {duration} to work on {item} before {day}",
        "add a study block for {item} {day}",
        "make time to finish {item} {day}",
        "reserve {duration} for {item} {day}",
        "create calendar time for {item} {day}",
        "block time for {item} before {day}",
    ]
    for item in work_items:
        for idx, day in enumerate(days):
            duration = durations[idx % len(durations)]
            for template in schedule_templates:
                add(
                    "propose_schedule_change",
                    template.format(item=item, day=day, duration=duration),
                )

    ai_templates = [
        "{topic}",
        "can you {topic}",
        "help me {topic}",
        "I need help with this: {topic}",
        "please {topic}",
    ]
    for topic in ai_topics:
        for template in ai_templates:
            add("ai_agent", template.format(topic=topic))

    examples: list[ConfidenceTestExample] = []
    for label in TOOL_LABEL_ORDER:
        items = pools[label]
        needed = target_counts[label]
        if len(items) < needed:
            raise RuntimeError(
                f"confidence test pool for {label} has {len(items)} prompts, "
                f"expected at least {needed}"
            )
        examples.extend(items[:needed])
    return examples


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = round((len(ordered) - 1) * percentile)
    return ordered[index]


def _print_table(rows: list[list[str]]) -> None:
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        print("  ".join(value.ljust(widths[i]) for i, value in enumerate(row)))


def run_confidence_test(
    agent: NlpToolCallingAgent,
    *,
    limit: int,
    list_limit: int,
    output_jsonl: str | None,
) -> int:
    if agent.intent_model is None:
        print(
            "[confidence-test] requires a trained model. Pass "
            "--model-dir /content/syntra_tool_router."
        )
        return 2

    examples = confidence_test_examples()
    if limit > 0:
        examples = examples[:limit]

    rows: list[dict[str, Any]] = []
    for ex in examples:
        model_predicted, model_confidence = agent.intent_model.predict(ex.text)
        planned = agent.plan(ex.text)
        call = planned[0] if planned else None
        predicted = call.name if call else "none"
        confidence = call.confidence if call else model_confidence
        needs_clarification = predicted == CLARIFICATION_ACTION
        rows.append(
            {
                "text": ex.text,
                "expected": ex.label,
                "predicted": predicted,
                "model_predicted": model_predicted,
                "confidence": round(confidence, 4),
                "model_confidence": round(model_confidence, 4),
                "trusted": not needs_clarification,
                "model_trusted": model_confidence >= agent.confidence_threshold,
                "needs_clarification": needs_clarification,
                "overridden": predicted != model_predicted and not needs_clarification,
                "correct": predicted == ex.label,
                "model_correct": model_predicted == ex.label,
            }
        )

    confidences = [float(row["confidence"]) for row in rows]
    model_confidences = [float(row["model_confidence"]) for row in rows]
    below_threshold = [row for row in rows if not row["model_trusted"]]
    clarifications = [row for row in rows if row["needs_clarification"]]
    overrides = [row for row in rows if row["overridden"]]
    mistakes = [row for row in rows if not row["correct"]]
    model_mistakes = [row for row in rows if not row["model_correct"]]
    correct = len(rows) - len(mistakes)
    summary = {
        "examples": len(rows),
        "correct": correct,
        "accuracy": round(correct / len(rows), 4) if rows else 0.0,
        "model_correct": len(rows) - len(model_mistakes),
        "model_accuracy": round((len(rows) - len(model_mistakes)) / len(rows), 4)
        if rows
        else 0.0,
        "confidence_threshold": agent.confidence_threshold,
        "model_below_threshold": len(below_threshold),
        "model_below_threshold_rate": round(len(below_threshold) / len(rows), 4)
        if rows
        else 0.0,
        "clarifications": len(clarifications),
        "overrides": len(overrides),
        "average_route_confidence": round(sum(confidences) / len(confidences), 4)
        if confidences
        else 0.0,
        "average_model_confidence": round(sum(model_confidences) / len(model_confidences), 4)
        if model_confidences
        else 0.0,
        "min_model_confidence": min(model_confidences) if model_confidences else 0.0,
        "p10_model_confidence": _percentile(model_confidences, 0.10),
        "p50_model_confidence": _percentile(model_confidences, 0.50),
    }
    print("[confidence-test] summary")
    print(json.dumps(summary, indent=2))

    support = Counter(row["expected"] for row in rows)
    correct_by_label = Counter(row["expected"] for row in rows if row["correct"])
    model_correct_by_label = Counter(row["expected"] for row in rows if row["model_correct"])
    low_by_label = Counter(row["expected"] for row in below_threshold)
    override_by_label = Counter(row["expected"] for row in overrides)
    confidence_sum = Counter(
        {
            label: sum(
                float(row["model_confidence"]) for row in rows if row["expected"] == label
            )
            for label in TOOL_LABEL_ORDER
        }
    )
    metric_rows = [["expected_label", "support", "accuracy", "model_acc", "avg_model_conf", "model_below", "overrides"]]
    for label in TOOL_LABEL_ORDER:
        count = support[label]
        accuracy = correct_by_label[label] / count if count else 0.0
        model_accuracy = model_correct_by_label[label] / count if count else 0.0
        avg_conf = confidence_sum[label] / count if count else 0.0
        metric_rows.append(
            [
                label,
                str(count),
                f"{accuracy:.3f}",
                f"{model_accuracy:.3f}",
                f"{avg_conf:.3f}",
                str(low_by_label[label]),
                str(override_by_label[label]),
            ]
        )
    print("\n[confidence-test] per-label")
    _print_table(metric_rows)

    print(f"\n[confidence-test] lowest model-confidence prompts: {len(below_threshold)} below threshold")
    for row in sorted(rows, key=lambda item: float(item["model_confidence"]))[:list_limit]:
        print(json.dumps(row, ensure_ascii=False))

    print(f"\n[confidence-test] final routing mistakes: {len(mistakes)}")
    for row in mistakes[:list_limit]:
        print(json.dumps(row, ensure_ascii=False))

    print(f"\n[confidence-test] raw model mistakes before overrides: {len(model_mistakes)}")
    for row in model_mistakes[:list_limit]:
        print(json.dumps(row, ensure_ascii=False))

    if output_jsonl:
        output_path = Path(output_jsonl)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"\n[confidence-test] wrote predictions to {output_path}")

    return 0


async def _main() -> int:
    parser = argparse.ArgumentParser(description="Route natural language to Synctra tools.")
    parser.add_argument("message", nargs="*", help="User request to route.")
    parser.add_argument(
        "--model-dir",
        default=os.getenv("SYNTRA_TOOL_ROUTER_MODEL"),
        help="Optional trained classifier directory from train_heavy_tool_router.py.",
    )
    parser.add_argument(
        "--confidence-threshold",
        type=float,
        default=float(os.getenv("SYNTRA_TOOL_ROUTER_THRESHOLD", "0.80")),
        help=(
            "Minimum classifier confidence before trusting a model label. "
            "Below this, the router asks a clarification first."
        ),
    )
    parser.add_argument(
        "--confidence-test",
        action="store_true",
        help="Score 1000 built-in labeled prompts and print confidence metrics.",
    )
    parser.add_argument(
        "--confidence-test-limit",
        type=int,
        default=1000,
        help="Number of built-in confidence-test prompts to score. Default: 1000.",
    )
    parser.add_argument(
        "--confidence-list-limit",
        type=int,
        default=25,
        help="How many low-confidence prompts and mistakes to print.",
    )
    parser.add_argument(
        "--confidence-output-jsonl",
        help="Optional path to write all confidence-test predictions as JSONL.",
    )
    parser.add_argument(
        "--after-clarification",
        action="store_true",
        help=(
            "Mark this message as the user's reply to a clarification question. "
            "If confidence is still below the threshold, route to ai_agent."
        ),
    )
    parser.add_argument(
        "--backend",
        action="store_true",
        help="Execute with backend chat tools instead of only printing planned calls.",
    )
    parser.add_argument(
        "--mock",
        action="store_true",
        help="Execute mock handlers and print mock results.",
    )
    parser.add_argument(
        "--fallback-colab",
        action="store_true",
        help="Execute ai_agent fallback by calling Colab /api/generate.",
    )
    parser.add_argument(
        "--colab-host",
        default=(
            os.getenv("COLAB_AI_AGENT_HOST")
            or os.getenv("COLAB_COURSE_IMPORT_HOST")
            or os.getenv("COLAB_LLM_HOST")
            or os.getenv("OLLAMA_HOST")
        ),
        help=(
            "Colab tunnel URL. Defaults to COLAB_AI_AGENT_HOST, "
            "COLAB_COURSE_IMPORT_HOST, COLAB_LLM_HOST, or OLLAMA_HOST."
        ),
    )
    parser.add_argument(
        "--colab-model",
        default=(
            os.getenv("COLAB_COURSE_MODEL")
            or os.getenv("OLLAMA_MODEL")
            or "Qwen/Qwen2.5-3B-Instruct"
        ),
        help="Model name sent to Colab /api/generate.",
    )
    parser.add_argument(
        "--today",
        help="Override today's date for testing, e.g. 2026-06-01.",
    )
    parser.add_argument(
        "--serve",
        action="store_true",
        help=(
            "Run as a FastAPI server exposing /plan and /health so the Synctra "
            "backend (in another Colab notebook) can reach the trained router."
        ),
    )
    parser.add_argument(
        "--serve-host",
        default=os.getenv("HOST", "0.0.0.0"),
        help="Bind address for --serve mode. Default 0.0.0.0.",
    )
    parser.add_argument(
        "--serve-port",
        type=int,
        default=int(os.getenv("PORT", "8000")),
        help="Port for --serve mode. Default 8000.",
    )
    parser.add_argument(
        "--ngrok-auth-token",
        default=os.getenv("NGROK_AUTH_TOKEN"),
        help="ngrok auth token used by --serve to open a public tunnel.",
    )
    parser.add_argument(
        "--no-tunnel",
        action="store_true",
        help="Skip ngrok in --serve mode; bind only to host/port.",
    )
    args, unknown = parser.parse_known_args(_strip_notebook_args(sys.argv[1:]))
    if unknown:
        print(f"[setup] ignoring unknown notebook args: {unknown}")
    if not args.message and not args.confidence_test and not args.serve:
        print(
            "No message provided. In Colab, either run this file with `!python` "
            "and a message, or import NlpToolCallingAgent and call agent.plan(...)."
        )
        return 0

    today = datetime.strptime(args.today, "%Y-%m-%d").date() if args.today else None
    agent = NlpToolCallingAgent(
        today=today,
        model_dir=args.model_dir,
        confidence_threshold=args.confidence_threshold,
    )

    if args.serve:
        return run_serve(
            agent,
            host=args.serve_host,
            port=args.serve_port,
            ngrok_auth_token=args.ngrok_auth_token,
            no_tunnel=args.no_tunnel,
        )

    if args.confidence_test:
        return run_confidence_test(
            agent,
            limit=args.confidence_test_limit,
            list_limit=args.confidence_list_limit,
            output_jsonl=args.confidence_output_jsonl,
        )

    message = " ".join(args.message)

    if args.backend:
        registry = backend_registry()
        registry["ai_agent"] = colab_ai_agent_handler(
            args.colab_host,
            model=args.colab_model,
        )
        output = await agent.run(
            message,
            registry,
            clarification_pending=args.after_clarification,
        )
    elif args.mock:
        registry = mock_registry()
        if args.fallback_colab:
            registry["ai_agent"] = colab_ai_agent_handler(
                args.colab_host,
                model=args.colab_model,
            )
        output = await agent.run(
            message,
            registry,
            clarification_pending=args.after_clarification,
        )
    elif args.fallback_colab:
        output = await agent.run(
            message,
            {
                "ai_agent": colab_ai_agent_handler(
                    args.colab_host,
                    model=args.colab_model,
                )
            },
            clarification_pending=args.after_clarification,
        )
    else:
        output = [
            asdict(call)
            for call in agent.plan(
                message,
                clarification_pending=args.after_clarification,
            )
        ]

    print(json.dumps(output, indent=2, default=_json_default))
    return 0


def _run_main() -> int:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(_main())

    try:
        import nest_asyncio
    except ImportError as exc:
        raise RuntimeError(
            "This CLI is running inside an active notebook event loop. "
            "In Colab, save it first with "
            "`%%writefile /content/nlp_tool_calling_agent.py`, then run it with "
            "`!python /content/nlp_tool_calling_agent.py ...`. "
            "Alternatively install nest_asyncio."
        ) from exc

    nest_asyncio.apply(loop)
    return loop.run_until_complete(_main())


if __name__ == "__main__":
    exit_code = _run_main()
    if exit_code:
        raise SystemExit(exit_code)
