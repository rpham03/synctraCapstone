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


def test_plan_this_week_routes_to_schedule_without_trained_model():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    call = agent.plan("plan this week")[0]

    assert call.name == "propose_schedule_change"
    assert call.arguments["task_name"]
    assert call.arguments["estimated_minutes"] >= 15
