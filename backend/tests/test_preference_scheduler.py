"""Tests for preference-based scheduling (suggest/apply)."""

from __future__ import annotations

import asyncio

from app.services import event_classification as clf
from app.services import preference_scheduler as sched
from app.services import productivity_preferences as prefs


def _ev(eid, title, source, start, end):
    return {"id": eid, "title": title, "source": source, "start_time": start, "end_time": end}


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
