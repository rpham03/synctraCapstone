from datetime import datetime, timedelta

from app.services.scheduler_service import (
    FixedEvent,
    SchedulerService,
    Task,
)


def test_suggest_places_block_when_calendar_free():
    svc = SchedulerService()
    window = datetime(2030, 1, 6, 9, 0, 0)
    due = window + timedelta(days=5)
    tasks = [
        Task(
            id="t1",
            title="Read chapter 1",
            due_date=due,
            estimated_minutes=60,
        )
    ]
    blocks = svc.suggest_blocks(
        tasks,
        [],
        look_ahead_days=7,
        window_start=window,
    )
    assert len(blocks) == 1
    b = blocks[0]
    assert b.task_id == "t1"
    assert b.end - b.start == timedelta(minutes=60)
    assert b.start >= window
    assert b.end <= due


def test_suggest_skips_slot_blocked_by_fixed_event():
    svc = SchedulerService()
    window = datetime(2030, 1, 6, 9, 0, 0)
    due = window + timedelta(days=2)
    fixed = [
        FixedEvent(start=window, end=window + timedelta(hours=8)),
    ]
    tasks = [
        Task(
            id="t1",
            title="Study",
            due_date=due,
            estimated_minutes=120,
        )
    ]
    blocks = svc.suggest_blocks(
        tasks,
        fixed,
        look_ahead_days=7,
        window_start=window,
    )
    assert len(blocks) == 1
    assert blocks[0].start >= window + timedelta(hours=8)
