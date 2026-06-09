"""Tests for preference-based scheduling (suggest/apply)."""

from __future__ import annotations

import asyncio

from app.services import event_classification as clf
from app.services import preference_scheduler as sched
from app.services import productivity_preferences as prefs


def _ev(eid, title, source, start, end):
    return {"id": eid, "title": title, "source": source, "start_time": start, "end_time": end}


def test_split_minutes_caps_sessions_at_two_hours():
    from app.services.preference_scheduler import _split_minutes

    assert _split_minutes(60) == [60]
    assert _split_minutes(120) == [120]
    assert _split_minutes(180) == [90, 90]   # 3h -> two 1.5h sessions
    assert _split_minutes(240) == [120, 120]  # 4h -> two 2h sessions
    assert _split_minutes(300) == [100, 100, 100]  # 5h -> three sessions


def test_suggest_splits_long_task_into_sessions_across_days(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "_store_path", tmp_path / "p.json")
    monkeypatch.setattr(clf, "_store_path", tmp_path / "c.json")

    from app.services import preference_scheduler as sched
    from app.services.chat_client_context import (
        clear_client_context,
        set_calendar_events,
        set_client_today,
        set_tasks,
        set_user_id,
    )

    try:
        set_user_id("u")
        set_client_today("2026-06-08")
        prefs.set_preferences("u", ["night"])
        set_calendar_events([])
        set_tasks([
            {"title": "Essay", "estimated_minutes": 240, "due_date": "2026-06-20T23:59:00"}
        ])
        result = sched.suggest_preference_schedule(user_id="u")
    finally:
        clear_client_context()

    essay = [p for p in result["proposals"] if "Essay" in p["task_title"]]
    assert len(essay) == 2  # 4h split into two sessions
    assert all(p["duration_minutes"] == 120 for p in essay)
    assert sum(p["duration_minutes"] for p in essay) == 240
    assert len({p["start_time"][:10] for p in essay}) == 2  # spread across two days
    assert {p["task_title"] for p in essay} == {"Essay (1/2)", "Essay (2/2)"}


def test_suggest_keeps_a_break_between_same_day_sessions(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "_store_path", tmp_path / "p.json")
    monkeypatch.setattr(clf, "_store_path", tmp_path / "c.json")

    from datetime import datetime, timedelta

    from app.services import preference_scheduler as sched
    from app.services.chat_client_context import (
        clear_client_context,
        set_calendar_events,
        set_client_today,
        set_tasks,
        set_user_id,
    )

    try:
        set_user_id("u")
        set_client_today("2026-06-08")
        prefs.set_preferences("u", ["night"])
        set_calendar_events([])
        set_tasks([
            {"title": "A", "estimated_minutes": 60, "due_date": "2026-06-20T23:59:00"},
            {"title": "B", "estimated_minutes": 60, "due_date": "2026-06-20T23:59:00"},
        ])
        result = sched.suggest_preference_schedule(user_id="u", break_minutes=15)
    finally:
        clear_client_context()

    blocks = sorted(result["proposals"], key=lambda p: p["start_time"])
    for a, b in zip(blocks, blocks[1:]):
        end_a = datetime.fromisoformat(a["end_time"])
        start_b = datetime.fromisoformat(b["start_time"])
        if end_a.date() == start_b.date():
            assert start_b >= end_a + timedelta(minutes=15)  # 15-min break kept


def test_seeded_suggest_is_deterministic_per_seed(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "_store_path", tmp_path / "p.json")
    monkeypatch.setattr(clf, "_store_path", tmp_path / "c.json")

    from app.services import preference_scheduler as sched
    from app.services.chat_client_context import (
        clear_client_context,
        set_calendar_events,
        set_client_today,
        set_tasks,
        set_user_id,
    )

    try:
        set_user_id("u")
        set_client_today("2026-06-08")
        prefs.set_preferences("u", ["night", "afternoon"])
        set_calendar_events([])
        set_tasks([
            {"title": "Essay", "estimated_minutes": 240, "due_date": "2026-06-20T23:59:00"},
            {"title": "Lab", "estimated_minutes": 120, "due_date": "2026-06-20T23:59:00"},
        ])
        first = sched.suggest_preference_schedule(user_id="u", seed=5)
        again = sched.suggest_preference_schedule(user_id="u", seed=5)
    finally:
        clear_client_context()

    assert [p["start_time"] for p in first["proposals"]] == [
        p["start_time"] for p in again["proposals"]
    ]


def test_router_try_again_regenerates_without_applying(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "_store_path", tmp_path / "p.json")
    monkeypatch.setattr(clf, "_store_path", tmp_path / "c.json")

    from app.services.chat_client_context import (
        clear_client_context,
        get_schedule_proposals,
        set_calendar_events,
        set_client_today,
        set_tasks,
        set_user_id,
    )
    from app.services.nlp_router_chat_service import (
        NlpRouterChatService,
        _pending_nlu_context,
    )

    service = NlpRouterChatService()

    async def run():
        set_user_id("u")
        set_client_today("2026-06-08")
        set_calendar_events([])
        set_tasks([
            {"title": "Essay", "estimated_minutes": 120, "due_date": "2026-06-20T23:59:00"}
        ])
        await service.run_turn("I'm productive at night", user_id="u")
        await service.run_turn("yes", user_id="u")  # first suggestion
        before = get_schedule_proposals()
        retry = await service.run_turn("try again", user_id="u")  # regenerate
        mid = get_schedule_proposals()
        applied = await service.run_turn("yes", user_id="u")  # apply
        after = get_schedule_proposals()
        return retry, applied, before, mid, after

    try:
        _pending_nlu_context.clear()
        retry, applied, before, mid, after = asyncio.run(run())
    finally:
        _pending_nlu_context.clear()
        clear_client_context()

    assert "apply these" in retry.lower()  # a fresh suggestion, not an apply
    assert before == [] and mid == []  # nothing written while previewing/retrying
    assert "applied" in applied.lower()
    assert len(after) >= 1


def test_suggest_never_moves_fixed_and_relocates_flexible(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "_store_path", tmp_path / "p.json")
    monkeypatch.setattr(clf, "_store_path", tmp_path / "c.json")

    from app.services.chat_client_context import (
        clear_client_context,
        set_calendar_events,
        set_client_today,
        set_user_id,
    )

    try:
        set_user_id("u")
        set_client_today("2026-06-08")
        prefs.set_preferences("u", ["night"])
        set_calendar_events(
            [
                _ev("fix1", "CSE 369 Lecture", "course", "2026-06-09T09:00:00", "2026-06-09T10:00:00"),
                _ev("flex1", "Study math", "study_block", "2026-06-09T14:00:00", "2026-06-09T15:00:00"),
            ]
        )
        result = sched.suggest_preference_schedule(user_id="u")
    finally:
        clear_client_context()

    moved_ids = {p.get("replace_block_id") for p in result["proposals"]}
    assert "fix1" not in moved_ids  # a fixed event is never moved
    assert "flex1" in moved_ids  # the flexible block is relocated toward night

    moved = next(p for p in result["proposals"] if p.get("replace_block_id") == "flex1")
    hour = int(moved["start_time"][11:13])
    assert hour >= 21 or hour == 0  # lands inside the night window


def test_router_suggest_requires_confirmation_before_applying(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "_store_path", tmp_path / "p.json")
    monkeypatch.setattr(clf, "_store_path", tmp_path / "c.json")

    from app.services.chat_client_context import (
        clear_client_context,
        get_schedule_proposals,
        set_calendar_events,
        set_client_today,
        set_user_id,
    )
    from app.services.nlp_router_chat_service import (
        NlpRouterChatService,
        _pending_nlu_context,
    )

    service = NlpRouterChatService()

    async def run():
        set_user_id("u")
        set_client_today("2026-06-08")
        set_calendar_events(
            [_ev("flex1", "Study math", "study_block", "2026-06-09T14:00:00", "2026-06-09T15:00:00")]
        )
        r1 = await service.run_turn("I'm productive at night", user_id="u")
        r2 = await service.run_turn("yes", user_id="u")
        before = get_schedule_proposals()
        r3 = await service.run_turn("yes", user_id="u")
        after = get_schedule_proposals()
        return r1, r2, r3, before, after

    try:
        _pending_nlu_context.clear()
        r1, r2, r3, before, after = asyncio.run(run())
    finally:
        _pending_nlu_context.clear()
        clear_client_context()

    assert "would you like me to suggest a schedule" in r1.lower()
    assert "apply these" in r2.lower()
    assert before == []  # suggestion is preview-only, nothing written yet
    assert len(after) >= 1  # applied only after the second confirmation
    assert "applied" in r3.lower()


# ---- Settings study-window / session / break (from the Settings screen) ------

def _pin_clock(monkeypatch):
    """Pin the scheduler's 'now'/'today' so window assertions are deterministic."""
    from datetime import date, datetime

    monkeypatch.setattr(sched, "effective_now", lambda: datetime(2026, 6, 8, 8, 0))
    monkeypatch.setattr(sched, "effective_today", lambda: date(2026, 6, 8))


def _study_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "_store_path", tmp_path / "p.json")
    monkeypatch.setattr(clf, "_store_path", tmp_path / "c.json")
    _pin_clock(monkeypatch)


def test_settings_window_overrides_saved_period(tmp_path, monkeypatch):
    _study_setup(tmp_path, monkeypatch)
    from app.services.chat_client_context import (
        clear_client_context,
        set_calendar_events,
        set_client_today,
        set_study_preferences,
        set_tasks,
        set_user_id,
    )

    try:
        set_user_id("u")
        set_client_today("2026-06-08")
        set_calendar_events([])
        prefs.set_preferences("u", ["night"])  # a saved period…
        # …but Settings sent an explicit afternoon window, which must win.
        set_study_preferences(
            {"start": "15:00", "end": "18:00", "session_minutes": 60, "break_minutes": 10}
        )
        set_tasks([{"title": "HW", "estimated_minutes": 60, "due_date": "2026-06-20T23:59:00"}])
        result = sched.suggest_preference_schedule(user_id="u")
    finally:
        clear_client_context()

    assert result["proposals"]
    for p in result["proposals"]:
        hour = int(p["start_time"][11:13])
        assert 15 <= hour < 18  # afternoon window, not the 9 PM night period


def test_settings_session_length_splits_long_task(tmp_path, monkeypatch):
    _study_setup(tmp_path, monkeypatch)
    from app.services.chat_client_context import (
        clear_client_context,
        set_calendar_events,
        set_client_today,
        set_study_preferences,
        set_tasks,
        set_user_id,
    )

    try:
        set_user_id("u")
        set_client_today("2026-06-08")
        set_calendar_events([])
        set_study_preferences(
            {"start": "15:00", "end": "22:00", "session_minutes": 60, "break_minutes": 10}
        )
        set_tasks([{"title": "HW6", "estimated_minutes": 180, "due_date": "2026-06-20T23:59:00"}])
        result = sched.suggest_preference_schedule(user_id="u")
    finally:
        clear_client_context()

    hw = [p for p in result["proposals"] if "HW6" in p["task_title"]]
    assert len(hw) == 3  # 180 / 60-min sessions
    assert all(p["duration_minutes"] == 60 for p in hw)


def test_settings_break_between_same_day_blocks(tmp_path, monkeypatch):
    _study_setup(tmp_path, monkeypatch)
    from datetime import datetime, timedelta

    from app.services.chat_client_context import (
        clear_client_context,
        set_calendar_events,
        set_client_today,
        set_study_preferences,
        set_tasks,
        set_user_id,
    )

    try:
        set_user_id("u")
        set_client_today("2026-06-08")
        set_calendar_events([])
        # A short window + a deadline today forces two sessions onto the same day.
        set_study_preferences(
            {"start": "15:00", "end": "19:00", "session_minutes": 60, "break_minutes": 20}
        )
        set_tasks([{"title": "HW", "estimated_minutes": 120, "due_date": "2026-06-08T19:00:00"}])
        result = sched.suggest_preference_schedule(user_id="u")
    finally:
        clear_client_context()

    blocks = sorted(result["proposals"], key=lambda p: p["start_time"])
    assert len(blocks) >= 2
    same_day_pairs = 0
    for a, b in zip(blocks, blocks[1:]):
        end_a = datetime.fromisoformat(a["end_time"])
        start_b = datetime.fromisoformat(b["start_time"])
        if end_a.date() == start_b.date():
            same_day_pairs += 1
            assert start_b >= end_a + timedelta(minutes=20)  # configured break kept
    assert same_day_pairs >= 1


def test_scheduler_never_schedules_outside_window(tmp_path, monkeypatch):
    _study_setup(tmp_path, monkeypatch)
    from app.services.chat_client_context import (
        clear_client_context,
        set_calendar_events,
        set_client_today,
        set_study_preferences,
        set_tasks,
        set_user_id,
    )

    try:
        set_user_id("u")
        set_client_today("2026-06-08")
        set_calendar_events([])
        set_study_preferences(
            {"start": "17:00", "end": "21:00", "session_minutes": 90, "break_minutes": 10}
        )
        set_tasks(
            [
                {"title": "A", "estimated_minutes": 90, "due_date": "2026-06-20T23:59:00"},
                {"title": "B", "estimated_minutes": 180, "due_date": "2026-06-20T23:59:00"},
            ]
        )
        result = sched.suggest_preference_schedule(user_id="u")
    finally:
        clear_client_context()

    for p in result["proposals"]:
        start_minute = int(p["start_time"][11:13]) * 60 + int(p["start_time"][14:16])
        end_minute = int(p["end_time"][11:13]) * 60 + int(p["end_time"][14:16])
        assert start_minute >= 17 * 60
        assert end_minute <= 21 * 60


# ---- router conversation: try-again / typo / yes-applies-latest -------------

def _router_study_env(monkeypatch, tmp_path):
    _study_setup(tmp_path, monkeypatch)
    from app.services.chat_client_context import (
        set_calendar_events,
        set_client_today,
        set_study_preferences,
        set_tasks,
        set_user_id,
    )

    set_user_id("u")
    set_client_today("2026-06-08")
    set_calendar_events([])
    set_study_preferences(
        {"start": "17:00", "end": "21:00", "session_minutes": 60, "break_minutes": 10}
    )
    set_tasks(
        [
            {"title": "HW6", "estimated_minutes": 60, "due_date": "2026-06-20T23:59:00"},
            {"title": "Lab", "estimated_minutes": 60, "due_date": "2026-06-20T23:59:00"},
        ]
    )


def test_router_try_again_and_typo_produce_different_valid_proposals(tmp_path, monkeypatch):
    from app.services.chat_client_context import clear_client_context, get_schedule_proposals
    from app.services.nlp_router_chat_service import NlpRouterChatService, _pending_nlu_context

    service = NlpRouterChatService()

    async def run():
        _router_study_env(monkeypatch, tmp_path)
        await service.run_turn("I'm productive at night", user_id="u")
        await service.run_turn("yes", user_id="u")  # proposal A
        a = list(_pending_nlu_context["u"]["preference_proposals"])
        r_b = await service.run_turn("try again", user_id="u")  # proposal B
        b = list(_pending_nlu_context["u"]["preference_proposals"])
        r_c = await service.run_turn("try aain", user_id="u")  # typo -> proposal C
        c = list(_pending_nlu_context["u"]["preference_proposals"])
        before = get_schedule_proposals()
        applied = await service.run_turn("yes", user_id="u")  # apply C
        after = get_schedule_proposals()
        return a, b, c, r_b, r_c, before, after, applied

    try:
        _pending_nlu_context.clear()
        a, b, c, r_b, r_c, before, after, applied = asyncio.run(run())
    finally:
        _pending_nlu_context.clear()
        clear_client_context()

    def sig(props):
        return sorted((p["task_title"], p["start_time"]) for p in props)

    # try again and the typo both stay on the scheduling flow (never Qwen).
    assert "apply these" in r_b.lower()
    assert "apply these" in r_c.lower()
    # Each regeneration is genuinely different.
    assert sig(a) != sig(b)
    assert sig(b) != sig(c)
    # Nothing written until "yes", which applies the LATEST (C), not A or B.
    assert before == []
    assert sig(after) == sig(c)
    assert "applied" in applied.lower()


def test_router_no_alternative_schedule_explains_instead_of_repeating(tmp_path, monkeypatch):
    from app.services.chat_client_context import (
        clear_client_context,
        get_schedule_proposals,
        set_calendar_events,
        set_client_today,
        set_study_preferences,
        set_tasks,
        set_user_id,
    )
    from app.services.nlp_router_chat_service import NlpRouterChatService, _pending_nlu_context

    service = NlpRouterChatService()

    async def run():
        _study_setup(tmp_path, monkeypatch)
        set_user_id("u")
        set_client_today("2026-06-08")
        set_calendar_events([])
        # Window fits exactly one 60-min block, and the deadline is today, so
        # there's a single valid arrangement — "try again" can't differ.
        set_study_preferences(
            {"start": "17:00", "end": "18:00", "session_minutes": 60, "break_minutes": 10}
        )
        set_tasks([{"title": "HW", "estimated_minutes": 60, "due_date": "2026-06-08T18:00:00"}])
        await service.run_turn("I'm productive at night", user_id="u")
        first = await service.run_turn("yes", user_id="u")
        retry = await service.run_turn("try again", user_id="u")
        still_pending = bool(_pending_nlu_context.get("u"))
        applied = await service.run_turn("yes", user_id="u")  # the one option still applies
        after = get_schedule_proposals()
        return first, retry, still_pending, applied, after

    try:
        _pending_nlu_context.clear()
        first, retry, still_pending, applied, after = asyncio.run(run())
    finally:
        _pending_nlu_context.clear()
        clear_client_context()

    assert "apply these" in first.lower()
    assert "only schedule" in retry.lower()  # explains, not a repeated block list
    assert still_pending  # the single valid proposal is preserved
    assert "applied" in applied.lower()
    assert len(after) == 1


def test_chat_service_uses_latest_study_window_each_request(tmp_path, monkeypatch):
    """The window sent with each request is honored — change it and the next
    suggestion uses the new one (mirrors changing Settings without a restart)."""

    _study_setup(tmp_path, monkeypatch)
    from app.services.chat_service import ChatService
    from app.services.nlp_router_chat_service import _pending_nlu_context

    service = ChatService()
    tasks = [{"title": "HW", "estimated_minutes": 60, "due_date": "2026-06-20T23:59:00"}]

    async def run():
        # Request 1: afternoon window 15:00-16:00.
        await service.process_message(
            "I'm productive at night",
            "u",
            calendar_events=[],
            tasks=tasks,
            client_today="2026-06-08",
            study_preferences={"start": "15:00", "end": "16:00", "session_minutes": 60, "break_minutes": 10},
        )
        await service.process_message(
            "yes",
            "u",
            calendar_events=[],
            tasks=tasks,
            client_today="2026-06-08",
            study_preferences={"start": "15:00", "end": "16:00", "session_minutes": 60, "break_minutes": 10},
        )
        # The suggestion is preview-only, so the proposed blocks live in pending.
        first = list(_pending_nlu_context["u"]["preference_proposals"])
        # Request 2 (Settings changed to evening 19:00-20:00): regenerate.
        await service.process_message(
            "try again",
            "u",
            calendar_events=[],
            tasks=tasks,
            client_today="2026-06-08",
            study_preferences={"start": "19:00", "end": "20:00", "session_minutes": 60, "break_minutes": 10},
        )
        latest = list(_pending_nlu_context["u"]["preference_proposals"])
        return first, latest

    try:
        _pending_nlu_context.clear()
        first, latest = asyncio.run(run())
    finally:
        _pending_nlu_context.clear()

    # First suggestion used the 3 PM window…
    assert first and all(int(p["start_time"][11:13]) == 15 for p in first)
    # …after Settings changed to 7 PM, the regenerated proposal uses 19:00.
    assert latest and all(int(p["start_time"][11:13]) == 19 for p in latest)


def test_router_bare_try_again_with_nothing_pending_asks_what_to_schedule(monkeypatch):
    from app.services.chat_client_context import clear_client_context, set_user_id
    from app.services.nlp_router_chat_service import NlpRouterChatService, _pending_nlu_context

    service = NlpRouterChatService()

    async def fail_plan(*_a, **_k):  # must not reach the router/AI agent
        raise AssertionError("a bare 'try again' with nothing pending must not plan")

    async def run():
        set_user_id("u")
        return await service.run_turn("try again", user_id="u")

    try:
        _pending_nlu_context.clear()
        monkeypatch.setattr(service, "_fetch_plan", fail_plan)
        reply = asyncio.run(run())
    finally:
        _pending_nlu_context.clear()
        clear_client_context()

    assert "don't have a schedule to redo" in reply.lower()


def test_default_daytime_window_when_no_prefs_or_settings(tmp_path, monkeypatch):
    """With no Settings window and no saved period, scheduling still works using
    a sensible daytime default (never overnight) with breaks — not a refusal."""

    _study_setup(tmp_path, monkeypatch)  # also pins now=08:00, today=2026-06-08
    from app.services.chat_client_context import (
        clear_client_context,
        set_calendar_events,
        set_client_today,
        set_tasks,
        set_user_id,
    )

    try:
        set_user_id("u")
        set_client_today("2026-06-08")
        set_calendar_events([])
        # No prefs.set_preferences and no set_study_preferences on purpose.
        set_tasks([{"title": "HW6", "estimated_minutes": 120, "due_date": "2026-06-20T23:59:00"}])
        result = sched.suggest_preference_schedule(user_id="u")
    finally:
        clear_client_context()

    assert result["proposals"]  # produced a schedule rather than refusing
    for p in result["proposals"]:
        hour = int(p["start_time"][11:13])
        assert 9 <= hour < 21  # default daytime window, never 3 AM
