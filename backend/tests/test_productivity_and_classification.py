"""Tests for productivity preferences and fixed/flexible event classification."""

from __future__ import annotations

import asyncio

from app.services import event_classification as clf
from app.services import productivity_preferences as prefs


# ---- productivity preferences ---------------------------------------------

def test_detect_periods_handles_phrasing_and_plurals():
    assert prefs.detect_periods("I'm productive at night") == ["night"]
    assert prefs.detect_periods("I work best in the mornings and evenings") == [
        "morning",
        "evening",
    ]
    assert prefs.detect_periods("nothing relevant here") == []


def test_set_get_remove_preferences_with_defaults_and_custom(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "_store_path", tmp_path / "prefs.json")
    user = "u1"

    saved = prefs.set_preferences(user, ["night"])
    assert saved == [{"period": "night", "start": "21:00", "end": "00:00"}]

    prefs.set_preferences(user, ["morning"])
    assert {p["period"] for p in prefs.get_preferences(user)} == {"morning", "night"}

    prefs.set_preferences(user, ["evening"], start="6pm", end="9pm")
    evening = next(p for p in prefs.get_preferences(user) if p["period"] == "evening")
    assert evening["start"] == "18:00" and evening["end"] == "21:00"

    prefs.remove_preferences(user, ["night"])
    assert "night" not in {p["period"] for p in prefs.get_preferences(user)}

    prefs.remove_preferences(user)
    assert prefs.get_preferences(user) == []


def test_preferences_are_isolated_per_user(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "_store_path", tmp_path / "prefs.json")
    prefs.set_preferences("a", ["night"])
    prefs.set_preferences("b", ["morning"])
    assert {p["period"] for p in prefs.get_preferences("a")} == {"night"}
    assert {p["period"] for p in prefs.get_preferences("b")} == {"morning"}


# ---- deterministic classification + safety rules --------------------------

def _ev(eid, title, source, start="2026-06-08T09:00:00", end="2026-06-08T10:00:00"):
    return {"id": eid, "title": title, "source": source, "start_time": start, "end_time": end}


def test_deterministic_safety_rules():
    assert clf.classify_deterministic(_ev("1", "CSE 369 Lecture", "course"))["fixed_or_flexible"] == "fixed"
    assert clf.classify_deterministic(_ev("2", "Study for CSE 369", "study_block"))["fixed_or_flexible"] == "flexible"
    assert clf.classify_deterministic(_ev("3", "Dentist", "manual"))["fixed_or_flexible"] == "fixed"
    assert clf.classify_deterministic(_ev("4", "Final Exam", "ical"))["fixed_or_flexible"] == "fixed"
    # Homework title with an unknown source is flexible by type.
    assert clf.classify_deterministic(_ev("5", "homework problem set", "other"))["fixed_or_flexible"] == "flexible"
    # No signal at all -> uncertain (ask the user).
    assert clf.classify_deterministic(_ev("6", "??", "weird"))["fixed_or_flexible"] == "uncertain"


def test_classify_all_counts_caches_and_reclassifies(tmp_path, monkeypatch):
    monkeypatch.setattr(clf, "_store_path", tmp_path / "clf.json")
    events = [_ev("a", "Lecture", "course"), _ev("b", "Study math", "study_block")]

    r1 = clf.classify_all_calendar_events(events, user_id="u")
    assert r1["counts"]["fixed"] == 1 and r1["counts"]["flexible"] == 1
    assert r1["counts"]["newly_classified"] == 2 and r1["counts"]["cached"] == 0

    r2 = clf.classify_all_calendar_events(events, user_id="u")
    assert r2["counts"]["cached"] == 2 and r2["counts"]["newly_classified"] == 0

    events[1] = _ev("b", "Study physics", "study_block")  # content changed
    r3 = clf.classify_all_calendar_events(events, user_id="u")
    assert r3["counts"]["newly_classified"] == 1


def test_ai_resolves_uncertain_events_and_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(clf, "_store_path", tmp_path / "clf.json")
    monkeypatch.setattr(clf, "_ai_host", lambda: "http://fake-agent")

    sent_payloads = []

    async def fake_call(host, payload):
        sent_payloads.append(payload)
        return [
            {
                "event_id": "x1",
                "event_name": "Mystery thing",
                "event_type": "personal",
                "fixed_or_flexible": "flexible",
                "confidence": 0.8,
                "reason": "Looks like a personal task.",
            }
        ]

    monkeypatch.setattr(clf, "_call_ai_agent", fake_call)

    events = [_ev("x1", "Mystery thing", "weird")]  # deterministic -> uncertain

    r1 = asyncio.run(clf.classify_all_calendar_events_with_ai(events, user_id="u"))
    resolved = r1["events"][0]
    assert resolved["fixed_or_flexible"] == "flexible"
    assert resolved["classified_by"] == "ai"
    assert r1["counts"]["ai_resolved"] == 1

    # The AI only saw id/name/type — never a description or other private data.
    assert sent_payloads and set(sent_payloads[0][0]) == {"event_id", "event_name", "event_type"}

    # Now cached — a plain deterministic run returns the AI verdict, no re-call.
    sent_payloads.clear()
    r2 = clf.classify_all_calendar_events(events, user_id="u")
    assert r2["events"][0]["fixed_or_flexible"] == "flexible"
    assert r2["counts"]["cached"] == 1


def test_ai_failure_leaves_event_uncertain(tmp_path, monkeypatch):
    monkeypatch.setattr(clf, "_store_path", tmp_path / "clf.json")
    monkeypatch.setattr(clf, "_ai_host", lambda: "http://fake-agent")

    async def boom(host, payload):
        raise clf.httpx.ConnectError("no agent")

    monkeypatch.setattr(clf, "_call_ai_agent", boom)

    events = [_ev("x2", "Mystery", "weird")]
    result = asyncio.run(clf.classify_all_calendar_events_with_ai(events, user_id="u"))
    assert result["events"][0]["fixed_or_flexible"] == "uncertain"  # graceful, not crashed


def test_ai_cannot_make_a_fixed_event_flexible(tmp_path, monkeypatch):
    monkeypatch.setattr(clf, "_store_path", tmp_path / "clf.json")
    monkeypatch.setattr(clf, "_ai_host", lambda: "http://fake-agent")

    # A course event is deterministically fixed, so it's never even sent to the AI.
    async def fake_call(host, payload):
        assert all(p["event_id"] != "c1" for p in payload)
        return []

    monkeypatch.setattr(clf, "_call_ai_agent", fake_call)
    events = [_ev("c1", "CSE 369 Lecture", "course")]
    result = asyncio.run(clf.classify_all_calendar_events_with_ai(events, user_id="u"))
    assert result["events"][0]["fixed_or_flexible"] == "fixed"


def test_user_override_persists_and_wins_over_rules(tmp_path, monkeypatch):
    monkeypatch.setattr(clf, "_store_path", tmp_path / "clf.json")
    assert clf.set_override("u", "ev1", "flexible") is True

    events = [_ev("ev1", "Dentist", "manual")]
    result = clf.classify_all_calendar_events(events, user_id="u")["events"][0]
    assert result["fixed_or_flexible"] == "flexible"
    assert result["classified_by"] == "override"
    # The rule alone would have said fixed.
    assert clf.classify_deterministic(events[0])["fixed_or_flexible"] == "fixed"


# ---- router end-to-end: save preference -> follow-up -> suggestion ---------

def test_router_preference_save_then_suggestion_followup(tmp_path, monkeypatch):
    monkeypatch.setattr(prefs, "_store_path", tmp_path / "prefs.json")
    monkeypatch.setattr(clf, "_store_path", tmp_path / "clf.json")

    from app.services.chat_client_context import (
        clear_client_context,
        set_calendar_events,
        set_user_id,
    )
    from app.services.nlp_router_chat_service import (
        NlpRouterChatService,
        _pending_nlu_context,
    )

    service = NlpRouterChatService()

    async def run():
        set_user_id("pu")
        set_calendar_events(
            [
                _ev("s1", "Study math", "study_block", "2026-06-08T20:00:00", "2026-06-08T21:00:00"),
                _ev("c1", "CSE 369 Lecture", "course", "2026-06-08T09:00:00", "2026-06-08T10:00:00"),
            ]
        )
        first = await service.run_turn("I'm productive at night", user_id="pu")
        second = await service.run_turn("yes", user_id="pu")
        return first, second

    try:
        _pending_nlu_context.clear()
        first, second = asyncio.run(run())
    finally:
        _pending_nlu_context.clear()
        clear_client_context()

    assert "saved night" in first.lower()
    assert "would you like me to suggest a schedule" in first.lower()
    # The follow-up suggestion lists the flexible study block, not the fixed class.
    assert "study math" in second.lower()
    assert "cse 369 lecture" not in second.lower()
    # And the preference was persisted.
    assert prefs.get_preferences("pu") == [{"period": "night", "start": "21:00", "end": "00:00"}]


def test_router_does_not_act_on_preference_statement_alone(tmp_path, monkeypatch):
    """A preference must never create/move/delete events by itself."""

    monkeypatch.setattr(prefs, "_store_path", tmp_path / "prefs.json")
    monkeypatch.setattr(clf, "_store_path", tmp_path / "clf.json")

    from app.services.chat_client_context import (
        clear_client_context,
        get_schedule_proposals,
        set_calendar_events,
        set_user_id,
    )
    from app.services.nlp_router_chat_service import (
        NlpRouterChatService,
        _pending_nlu_context,
    )

    service = NlpRouterChatService()

    async def run():
        set_user_id("pu2")
        set_calendar_events([])
        reply = await service.run_turn("I work best in the morning", user_id="pu2")
        return reply, get_schedule_proposals()

    try:
        _pending_nlu_context.clear()
        reply, proposals = asyncio.run(run())
    finally:
        _pending_nlu_context.clear()
        clear_client_context()

    assert "saved morning" in reply.lower()
    assert proposals == []
