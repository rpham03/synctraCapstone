"""Regression tests for the standalone NLP tool router."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_DIR = REPO_ROOT / "tool"
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from nlp_tool_calling_agent import NlpToolCallingAgent


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


def test_add_calendar_block_routes_to_schedule_without_trained_model():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    call = agent.plan("add a block to my calendar tomorrow")[0]

    assert call.name == "propose_schedule_change"
    assert call.arguments["task_name"]
    assert call.arguments["estimated_minutes"] >= 15
    assert call.arguments["deadline"].startswith("2026-06-04")


def test_add_calendar_block_overrides_trained_calendar_prediction():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    class FakeIntentModel:
        def predict(self, message: str) -> tuple[str, float]:
            return "get_calendar_events", 0.99

    agent.intent_model = FakeIntentModel()  # type: ignore[assignment]

    call = agent.plan("add a block to my calendar tomorrow")[0]

    assert call.name == "propose_schedule_change"
