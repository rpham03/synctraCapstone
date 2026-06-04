"""Tests for chat agent tools and OpenAI wiring."""

import asyncio
import json
from unittest.mock import patch

import httpx

from app.services import chat_agent_tools
from app.services.chat_service import ChatService


def test_normalize_reply_times_converts_military():
    from app.services.chat_agent_common import normalize_reply_times

    assert "6:45 PM" in normalize_reply_times("from 18:45 to 19:45")
    assert "18:45" not in normalize_reply_times("from 18:45 to 19:45")
    assert normalize_reply_times("from 12:30 PM to 1:20 PM") == (
        "from 12:30 PM to 1:20 PM"
    )


def test_sanitize_chat_reply_strips_debug_dump():
    from app.services.chat_agent_common import sanitize_chat_reply

    raw = "Busy: [], Tasks: [],\nAssignments: []"
    cleaned = sanitize_chat_reply(raw)
    assert "Busy:" not in cleaned
    assert "Tasks:" not in cleaned
    assert "Assignments:" not in cleaned
    assert len(cleaned) > 20


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
    from app.services.chat_client_context import clear_client_context, set_calendar_events

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
        clear_client_context()
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
    assert result.get("total_estimated_minutes") == 120


def test_list_calendar_events_from_client_context():
    from app.services.chat_client_context import clear_client_context, set_calendar_events

    day = chat_agent_tools.today_local().isoformat()
    set_calendar_events(
        [
            {
                "start_time": f"{day}T10:00:00",
                "end_time": f"{day}T11:00:00",
                "title": "CSE 331 Lecture",
                "source": "course",
            }
        ]
    )
    try:
        result = chat_agent_tools.list_calendar_events_for_range(day, day)
    finally:
        clear_client_context()
    assert result["count"] == 1
    assert "CSE 331" in result["events"][0]["title"]
    assert result["events"][0]["time_label"] == "10:00 AM – 11:00 AM"


def test_list_tasks_from_client_context():
    from app.services.chat_client_context import clear_client_context, set_tasks

    day = chat_agent_tools.today_local().isoformat()
    set_tasks(
        [
            {
                "id": "t1",
                "title": "Problem set 3",
                "due_date": f"{day}T23:59:00",
                "estimated_minutes": 90,
                "course_name": "CSE 331",
                "source": "manual",
                "is_completed": False,
            }
        ]
    )
    try:
        result = chat_agent_tools.list_tasks_for_range(day, day)
    finally:
        clear_client_context()
    assert result["count"] == 1
    assert result["tasks"][0]["display_label"] == "CSE 331 — Problem set 3"
    assert result["tasks"][0]["estimated_minutes"] == 90
    assert "due_label" in result["tasks"][0]


def test_propose_schedule_change_splits_long_sessions():
    from app.services.chat_client_context import clear_client_context, set_calendar_events

    set_calendar_events([])
    try:
        result = chat_agent_tools.propose_schedule_change(
            "Big project",
            0,
            "2035-06-01T23:59:00",
            estimated_minutes=180,
        )
    finally:
        clear_client_context()
    assert len(result["proposal"]) >= 2
    assert result["session_count"] >= 2
    assert sum(p["duration_minutes"] for p in result["proposal"]) == 180


def test_propose_schedule_change_uses_client_local_window_start(monkeypatch):
    from datetime import datetime, timedelta

    from app.services.scheduler_service import ScheduleBlock

    local_now = datetime(2026, 6, 3, 21, 30, 0)
    captured: dict[str, object] = {}

    def fake_suggest_task_sessions(
        self,
        task,
        fixed_events,
        look_ahead_days=7,
        *,
        window_start=None,
        max_block_minutes=90,
    ):
        captured["window_start"] = window_start
        return [
            ScheduleBlock(
                id="block-1",
                task_id=task.id,
                task_title=task.title,
                start=local_now,
                end=local_now + timedelta(minutes=60),
            )
        ]

    monkeypatch.setattr(chat_agent_tools, "effective_now", lambda: local_now)
    monkeypatch.setattr(
        chat_agent_tools.SchedulerService,
        "suggest_task_sessions",
        fake_suggest_task_sessions,
    )

    result = chat_agent_tools.propose_schedule_change(
        "Plan this week",
        1.0,
        "2026-06-05T23:59:00",
    )

    assert captured["window_start"] == local_now
    assert result["proposal"][0]["start_time"] == local_now.isoformat()


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
    reply, _ = asyncio.run(service.process_message("What is due this week?", "u1"))
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
        reply, _ = asyncio.run(service.process_message("Plan my week", "u2"))
        assert reply == "Here is your plan."


def test_chat_service_nlp_mocked(monkeypatch):
    import app.core.config.settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "chat_llm_provider", "nlp")
    service = ChatService()

    async def _fake_nlp_turn(*_args, **_kwargs):
        return "Here is your NLP-routed answer."

    class FakeNlpAgent:
        run_turn = _fake_nlp_turn

    monkeypatch.setattr(service, "_nlp_agent", lambda: FakeNlpAgent())
    reply, proposals = asyncio.run(
        service.process_message("What is due this week?", "u-nlp")
    )
    assert reply == "Here is your NLP-routed answer."
    assert proposals == []


def test_chat_service_nlp_returns_schedule_proposals(monkeypatch):
    import app.core.config.settings as settings_mod
    from app.services.chat_client_context import append_schedule_proposals

    monkeypatch.setattr(settings_mod.settings, "chat_llm_provider", "nlp")
    service = ChatService()

    async def _fake_nlp_turn(*_args, **_kwargs):
        append_schedule_proposals(
            [
                {
                    "task_title": "Problem set",
                    "start_time": "2026-06-03T09:00:00",
                    "end_time": "2026-06-03T10:00:00",
                    "duration_minutes": 60,
                    "is_ai_generated": True,
                }
            ]
        )
        return "I added this study block to your calendar preview."

    class FakeNlpAgent:
        run_turn = _fake_nlp_turn

    monkeypatch.setattr(service, "_nlp_agent", lambda: FakeNlpAgent())
    reply, proposals = asyncio.run(service.process_message("Plan this week", "u-nlp"))

    assert reply == "I added this study block to your calendar preview."
    assert proposals == [
        {
            "task_title": "Problem set",
            "start_time": "2026-06-03T09:00:00",
            "end_time": "2026-06-03T10:00:00",
            "duration_minutes": 60,
            "is_ai_generated": True,
        }
    ]


def test_add_calendar_block_tool_appends_preview_block():
    from app.services.chat_agent_common import execute_tool
    from app.services.chat_client_context import (
        clear_client_context,
        get_schedule_proposals,
    )

    async def run_add_block():
        result = await execute_tool(
            "add_calendar_block",
            {
                "title": "Study for math",
                "start_time": "2026-06-04T14:00:00",
                "end_time": "2026-06-04T15:00:00",
            },
        )
        return result, get_schedule_proposals()

    try:
        result, proposals = asyncio.run(run_add_block())
    finally:
        clear_client_context()

    assert result["message"] == "I added this calendar block to your calendar preview."
    assert proposals == [
        {
            "task_title": "Study for math",
            "start_time": "2026-06-04T14:00:00",
            "end_time": "2026-06-04T15:00:00",
            "duration_minutes": None,
            "is_ai_generated": False,
            "written_to_calendar": False,
        }
    ]


def test_nlp_router_run_turn_adds_calendar_block(monkeypatch):
    from app.services.chat_client_context import clear_client_context, get_schedule_proposals
    from app.services.nlp_router_chat_service import NlpRouterChatService

    service = NlpRouterChatService()

    async def fake_fetch_plan(*_args, **_kwargs):
        return [
            {
                "name": "add_calendar_block",
                "arguments": {
                    "title": "Study for math",
                    "start_time": "2026-06-04T14:00:00",
                    "end_time": "2026-06-04T15:00:00",
                },
            }
        ]

    async def run_turn():
        reply = await service.run_turn("add calendar block")
        return reply, get_schedule_proposals()

    try:
        monkeypatch.setattr(service, "_fetch_plan", fake_fetch_plan)
        reply, proposals = asyncio.run(run_turn())
    finally:
        clear_client_context()

    assert "I added this calendar block" in reply
    assert "Study for math" in reply
    assert proposals[0]["task_title"] == "Study for math"


def test_nlp_router_ai_agent_host_falls_back_to_router(monkeypatch):
    import app.core.config.settings as settings_mod
    from app.services.nlp_router_chat_service import NlpRouterChatService

    for key in (
        "COLAB_AI_AGENT_HOST",
        "COLAB_COURSE_IMPORT_HOST",
        "OLLAMA_HOST",
        "COLAB_NLP_ROUTER_HOST",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(settings_mod.settings, "colab_ai_agent_host", "")
    monkeypatch.setattr(settings_mod.settings, "colab_course_import_host", "")
    monkeypatch.setattr(settings_mod.settings, "colab_nlp_router_host", "https://router.example")

    assert NlpRouterChatService()._ai_agent_host() == "https://router.example"


def test_nlp_router_ai_agent_host_uses_configured_ollama(monkeypatch):
    import app.core.config.settings as settings_mod
    from app.services.nlp_router_chat_service import NlpRouterChatService

    for key in (
        "COLAB_AI_AGENT_HOST",
        "COLAB_COURSE_IMPORT_HOST",
        "OLLAMA_HOST",
        "COLAB_NLP_ROUTER_HOST",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(settings_mod.settings, "colab_ai_agent_host", "")
    monkeypatch.setattr(settings_mod.settings, "colab_course_import_host", "")
    monkeypatch.setattr(settings_mod.settings, "ollama_host", "https://ollama.example")
    monkeypatch.setattr(settings_mod.settings, "colab_nlp_router_host", "https://router.example")

    assert NlpRouterChatService()._ai_agent_host() == "https://ollama.example"


def test_nlp_router_calls_ollama_generate_for_ai_agent(monkeypatch):
    import app.core.config.settings as settings_mod
    from app.services.nlp_router_chat_service import NlpRouterChatService

    monkeypatch.setattr(settings_mod.settings, "colab_ai_agent_host", "")
    monkeypatch.setattr(settings_mod.settings, "colab_course_import_host", "")
    monkeypatch.setattr(settings_mod.settings, "colab_nlp_router_host", "")
    monkeypatch.setenv("OLLAMA_HOST", "https://ollama.example")
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["payload"] = json.loads(request.content.decode("utf-8"))
        return httpx.Response(200, json={"response": "Hello from ai_agent"})

    async def run() -> dict[str, object]:
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await NlpRouterChatService()._call_ai_agent(client, "hi")

    result = asyncio.run(run())

    assert result["assistant_message"] == "Hello from ai_agent"
    assert seen["url"] == "https://ollama.example/api/generate"
    assert seen["headers"]["ngrok-skip-browser-warning"] == "true"
    assert seen["payload"]["prompt"] == "hi"
    assert seen["payload"]["options"]["syntra_mode"] == "ai_agent"


def test_nlp_router_run_turn_uses_ai_agent_plan(monkeypatch):
    from app.services.nlp_router_chat_service import NlpRouterChatService

    service = NlpRouterChatService()
    seen: dict[str, str] = {}

    async def fake_fetch_plan(*_args, **_kwargs):
        return [{"name": "ai_agent", "arguments": {"message": "hi"}}]

    async def fake_call_ai_agent(_client, message: str):
        seen["message"] = message
        return {"assistant_message": "Hello from the Ollama ai_agent"}

    monkeypatch.setattr(service, "_fetch_plan", fake_fetch_plan)
    monkeypatch.setattr(service, "_call_ai_agent", fake_call_ai_agent)

    reply = asyncio.run(service.run_turn("hi"))

    assert seen["message"] == "hi"
    assert reply == "Hello from the Ollama ai_agent"


def test_nlp_router_unsupported_tool_falls_back_to_ai_agent(monkeypatch):
    from app.services.nlp_router_chat_service import NlpRouterChatService

    service = NlpRouterChatService()
    seen: dict[str, str] = {}

    async def fake_fetch_plan(*_args, **_kwargs):
        return [
            {
                "name": "find_free_slots",
                "arguments": {"start_date": "2026-06-03", "end_date": "2026-06-03"},
            }
        ]

    async def fake_call_ai_agent(_client, message: str):
        seen["message"] = message
        return {"assistant_message": "Qwen handled this generally"}

    monkeypatch.setattr(service, "_fetch_plan", fake_fetch_plan)
    monkeypatch.setattr(service, "_call_ai_agent", fake_call_ai_agent)

    reply = asyncio.run(service.run_turn("when am I free today"))

    assert seen["message"] == "when am I free today"
    assert reply == "Qwen handled this generally"


def test_nlp_router_empty_plan_falls_back_to_ai_agent(monkeypatch):
    from app.services.nlp_router_chat_service import NlpRouterChatService

    service = NlpRouterChatService()
    seen: dict[str, str] = {}

    async def fake_fetch_plan(*_args, **_kwargs):
        return []

    async def fake_call_ai_agent(_client, message: str):
        seen["message"] = message
        return {"assistant_message": "Qwen fallback"}

    monkeypatch.setattr(service, "_fetch_plan", fake_fetch_plan)
    monkeypatch.setattr(service, "_call_ai_agent", fake_call_ai_agent)

    reply = asyncio.run(service.run_turn("tell me a joke"))

    assert seen["message"] == "tell me a joke"
    assert reply == "Qwen fallback"


def test_nlp_router_verifies_generic_schedule_before_executing(monkeypatch):
    from app.services.chat_client_context import clear_client_context, get_schedule_proposals
    from app.services.nlp_router_chat_service import NlpRouterChatService

    service = NlpRouterChatService()

    async def fake_fetch_plan(*_args, **_kwargs):
        return [
            {
                "name": "propose_schedule_change",
                "arguments": {
                    "task_name": "this week",
                    "hours": 1,
                    "deadline": "2026-06-05T23:59:00",
                    "estimated_minutes": 60,
                },
            }
        ]

    try:
        monkeypatch.setattr(service, "_fetch_plan", fake_fetch_plan)
        reply = asyncio.run(service.run_turn("plan this week"))
        proposals = get_schedule_proposals()
    finally:
        clear_client_context()

    assert "what event name" in reply.lower()
    assert proposals == []


def test_nlp_router_verifies_calendar_block_times_before_executing(monkeypatch):
    from app.services.chat_client_context import clear_client_context, get_schedule_proposals
    from app.services.nlp_router_chat_service import NlpRouterChatService

    service = NlpRouterChatService()

    async def fake_fetch_plan(*_args, **_kwargs):
        return [
            {
                "name": "add_calendar_block",
                "arguments": {
                    "title": "Study for CSE 369",
                    "start_time": "2026-06-04T21:00:00",
                    "end_time": "2026-06-04T19:00:00",
                },
            }
        ]

    try:
        monkeypatch.setattr(service, "_fetch_plan", fake_fetch_plan)
        reply = asyncio.run(
            service.run_turn("study for cse 369 thursday from 9pm to 7pm")
        )
        proposals = get_schedule_proposals()
    finally:
        clear_client_context()

    assert "end time must be after" in reply.lower()
    assert proposals == []


def test_nlp_router_verifies_calendar_details_misrouted_to_schedule(monkeypatch):
    from app.services.chat_client_context import clear_client_context, get_schedule_proposals
    from app.services.nlp_router_chat_service import NlpRouterChatService

    service = NlpRouterChatService()

    async def fake_fetch_plan(*_args, **_kwargs):
        return [
            {
                "name": "propose_schedule_change",
                "arguments": {
                    "task_name": "study for cse 369",
                    "hours": 1,
                    "deadline": "2026-06-04T23:59:00",
                    "estimated_minutes": 60,
                },
            }
        ]

    try:
        monkeypatch.setattr(service, "_fetch_plan", fake_fetch_plan)
        reply = asyncio.run(
            service.run_turn("study for cse 369 on thursday 4th at 7pm to 9 pm")
        )
        proposals = get_schedule_proposals()
    finally:
        clear_client_context()

    assert "calendar block" in reply.lower()
    assert proposals == []


def test_chat_service_openai_mocked(monkeypatch):
    import app.core.config.settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "chat_llm_provider", "openai")
    monkeypatch.setattr(settings_mod.settings, "openai_api_key", "sk-test")
    service = ChatService()
    with patch(
        "app.services.chat_service.OpenAIAgentService.run_turn",
        side_effect=_fake_run_turn,
    ):
        reply, _ = asyncio.run(service.process_message("Plan my week", "u3"))
        assert reply == "Here is your plan."
