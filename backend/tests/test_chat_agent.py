"""Tests for chat agent tools and OpenAI wiring."""

import asyncio
from unittest.mock import patch

from app.services import chat_agent_tools
from app.services.chat_service import ChatService


def test_get_assignments_without_canvas_token(monkeypatch):
    import app.core.config.settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "canvas_api_token", "")
    result = asyncio.run(chat_agent_tools.get_assignments_from_canvas())
    assert result["assignments"] == []
    assert "error" in result


def test_find_free_slots_returns_workday_windows():
    result = chat_agent_tools.find_free_slots_in_calendar(
        "2026-05-12",
        "2026-05-13",
    )
    assert "slots" in result
    assert len(result["slots"]) >= 1


def test_find_free_slots_respects_busy_calendar_events():
    from app.services.chat_calendar_context import set_calendar_events

    # Use today so sanitize_free_slot_range does not rewrite to Mon–Fri (which
    # would leave other days as one long slot and break the assertion below).
    day = chat_agent_tools.today_local().isoformat()
    set_calendar_events(
        [
            {
                "start_time": f"{day}T14:30:00",
                "end_time": f"{day}T15:20:00",
                "title": "Lecture",
            }
        ]
    )
    try:
        result = chat_agent_tools.find_free_slots_in_calendar(day, day)
    finally:
        set_calendar_events(None)
    assert result["calendar_events_used"] == 1
    slots = result["slots"]
    assert len(slots) >= 2
    # No single slot should span the entire work day (lecture splits the day)
    assert all(s["minutes_available"] < 8 * 60 for s in slots)


def test_sanitize_stale_march_dates_to_current_week():
    start, end, corrected = chat_agent_tools.sanitize_free_slot_range(
        "2026-03-06",
        "2026-03-10",
    )
    assert corrected is True
    today = chat_agent_tools.today_local()
    mon, fri = chat_agent_tools.week_range_mon_fri(today)
    assert start == mon
    assert end == fri


def test_propose_schedule_change_returns_blocks():
    result = chat_agent_tools.propose_schedule_change(
        "CSE project",
        2.0,
        "2035-06-01T23:59:00",
    )
    assert result.get("proposal")
    assert result["proposal"][0]["written_to_calendar"] is False


def test_chat_service_fallback_without_llm(monkeypatch):
    import app.core.config.settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "openai_api_key", "")
    monkeypatch.setattr(settings_mod.settings, "chat_llm_provider", "none-invalid")
    service = ChatService()
    # Force fallback by patching provider to something that won't match
    monkeypatch.setattr(
        service,
        "_provider",
        lambda: "disabled",
    )
    reply = asyncio.run(service.process_message("What is due this week?", "u1"))
    assert "Tasks" in reply or "Ollama" in reply


async def _fake_run_turn(*_args, **_kwargs):
    return "Here is your plan."


def test_chat_service_ollama_mocked(monkeypatch):
    import app.core.config.settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "chat_llm_provider", "ollama")
    monkeypatch.setattr(settings_mod.settings, "openai_api_key", "")
    service = ChatService()
    with patch(
        "app.services.chat_service.OllamaAgentService.run_turn",
        side_effect=_fake_run_turn,
    ):
        reply = asyncio.run(service.process_message("Plan my week", "u2"))
    assert reply == "Here is your plan."


def test_chat_service_openai_mocked(monkeypatch):
    import app.core.config.settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "chat_llm_provider", "openai")
    monkeypatch.setattr(settings_mod.settings, "openai_api_key", "sk-test")
    service = ChatService()
    with patch(
        "app.services.chat_service.OpenAIAgentService.run_turn",
        side_effect=_fake_run_turn,
    ):
        reply = asyncio.run(service.process_message("Plan my week", "u3"))
    assert reply == "Here is your plan."
