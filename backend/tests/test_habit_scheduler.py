"""Tests for habit scheduling engine, scoring, and conflict rescheduling."""
from datetime import datetime, timedelta

import pytest

from app.models.habit_models import CalendarEvent, Habit, HabitSession, TimeRange
from app.services.habit_conflict_detection import find_conflicting_sessions
from app.services.habit_repository import HabitRepository
from app.services.habit_rescheduling_service import HabitReschedulingService
from app.services.habit_scheduling_engine import HabitSchedulingEngine
from app.services.habit_slot_scoring import score_candidate


def _lunch_habit() -> Habit:
    return Habit(
        id="h1",
        user_id="u1",
        title="Lunch",
        duration_minutes=60,
        frequency_per_week=5,
        preferred_days=[0, 1, 2, 3, 4],
        preferred_time_ranges={
            0: [TimeRange(start_minutes=11 * 60 + 30, end_minutes=14 * 60)],
            1: [TimeRange(start_minutes=11 * 60 + 30, end_minutes=14 * 60)],
            2: [TimeRange(start_minutes=11 * 60 + 30, end_minutes=14 * 60)],
            3: [TimeRange(start_minutes=11 * 60 + 30, end_minutes=14 * 60)],
            4: [TimeRange(start_minutes=11 * 60 + 30, end_minutes=14 * 60)],
        },
        priority=9,
    )


def test_calendar_event_blocks_habit_placement():
    engine = HabitSchedulingEngine()
    week = datetime(2030, 6, 3, 0, 0, 0)  # Monday
    fixed = [
        CalendarEvent(
            id="class",
            title="Lecture",
            start=datetime(2030, 6, 3, 12, 0),
            end=datetime(2030, 6, 3, 13, 30),
        )
    ]
    sessions = engine.schedule_habits_fresh([_lunch_habit()], fixed, week_start=week)
    assert len(sessions) == 5
    monday = [s for s in sessions if s.start.weekday() == 0][0]
    assert monday.start.hour >= 13 or monday.start.hour < 12
    assert monday.start.hour * 60 + monday.start.minute >= 13 * 60 + 30 or monday.start.hour < 12
    assert "Tuesday" in sessions[1].explanation or "Monday" in monday.explanation


def test_scoring_prefers_preferred_day_and_time():
    habit = _lunch_habit()
    start = datetime(2030, 6, 3, 12, 0)  # Monday noon
    end = start + timedelta(hours=1)
    scored = score_candidate(
        habit,
        start,
        end,
        existing_sessions=[],
        day_session_counts={},
        week_session_count_for_habit=0,
    )
    assert scored.score > 40
    assert "Monday" in scored.explanation
    assert "matched" in scored.explanation


def test_conflict_detection_finds_overlapping_sessions():
    session = HabitSession(
        id="s1",
        habit_id="h1",
        habit_title="Lunch",
        start=datetime(2030, 6, 3, 12, 0),
        end=datetime(2030, 6, 3, 13, 0),
        explanation="",
    )
    hits = find_conflicting_sessions(
        [session],
        datetime(2030, 6, 3, 12, 30),
        datetime(2030, 6, 3, 13, 30),
    )
    assert len(hits) == 1


def test_reschedule_moves_conflicting_habit():
    habit = _lunch_habit()
    week = datetime(2030, 6, 3, 0, 0, 0)
    engine = HabitSchedulingEngine()
    sessions = engine.schedule_habits_fresh([habit], [], week_start=week)
    monday_session = next(s for s in sessions if s.start.weekday() == 0)

    new_event = CalendarEvent(
        id="meet",
        title="Team sync",
        start=monday_session.start,
        end=monday_session.end,
    )
    rescheduler = HabitReschedulingService(engine)
    updated, log = rescheduler.reschedule_after_new_event(
        habits=[habit],
        calendar_events=[],
        current_sessions=sessions,
        new_event=new_event,
        week_start=week,
    )
    assert len(updated) == len(sessions)
    new_monday = [s for s in updated if s.start.weekday() == 0]
    assert not any(
        s.start == monday_session.start and s.end == monday_session.end
        for s in new_monday
    )
    assert any(entry["action"] == "rescheduled" for entry in log)


def test_habit_repository_crud(tmp_path, monkeypatch):
    store = tmp_path / "habits.json"
    monkeypatch.setattr("app.services.habit_repository._store_path", store)
    repo = HabitRepository()
    created = repo.create(
        "user-a",
        {
            "title": "Gym",
            "duration_minutes": 45,
            "frequency_per_week": 3,
            "preferred_days": [1, 3, 5],
            "preferred_time_ranges": {
                "1": [{"start": "6:00pm", "end": "9:00pm"}],
            },
            "priority": 7,
        },
    )
    assert created.title == "Gym"
    listed = repo.list_for_user("user-a")
    assert len(listed) == 1
    updated = repo.update("user-a", created.id, {"priority": 10})
    assert updated.priority == 10
    assert repo.delete("user-a", created.id)
    assert repo.list_for_user("user-a") == []
