"""Regression tests for the standalone NLP tool router."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_DIR = REPO_ROOT / "tool"
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from nlp_tool_calling_agent import (
    ADD_CALENDAR_BLOCK_ACTION,
    CLARIFICATION_ACTION,
    NlpToolCallingAgent,
)


def test_greeting_routes_to_ai_agent_without_trained_model():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    call = agent.plan("hi")[0]

    assert call.name == "ai_agent"
    assert call.arguments["message"] == "hi"


def test_emotional_support_routes_to_ai_agent_without_trained_model():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    call = agent.plan("i feel stressed")[0]

    assert call.name == "ai_agent"
    assert call.arguments["message"] == "i feel stressed"


def test_plan_this_week_routes_to_schedule_without_trained_model():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    call = agent.plan("plan this week")[0]

    assert call.name == "propose_schedule_change"
    assert call.arguments["task_name"]
    assert call.arguments["estimated_minutes"] >= 15


def test_incomplete_calendar_block_asks_for_details_without_trained_model():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    call = agent.plan("add a block to my calendar tomorrow")[0]

    assert call.name == CLARIFICATION_ACTION
    assert call.arguments["predicted_tool"] == ADD_CALENDAR_BLOCK_ACTION
    assert "event name" in call.arguments["question"]
    assert "start and end time" in call.arguments["question"]


def test_complete_calendar_block_routes_to_add_block_without_trained_model():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    call = agent.plan(
        "add calendar block study for math tomorrow from 2 PM to 3 PM"
    )[0]

    assert call.name == ADD_CALENDAR_BLOCK_ACTION
    assert call.arguments == {
        "title": "study for math",
        "start_time": "2026-06-04T14:00:00",
        "end_time": "2026-06-04T15:00:00",
    }


def test_calendar_block_overrides_trained_calendar_prediction():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    class FakeIntentModel:
        def predict(self, message: str) -> tuple[str, float]:
            return "get_calendar_events", 0.99

    agent.intent_model = FakeIntentModel()  # type: ignore[assignment]

    call = agent.plan(
        "add calendar block study for math tomorrow from 2 PM to 3 PM"
    )[0]

    assert call.name == ADD_CALENDAR_BLOCK_ACTION
