# Core scheduling service — places flexible study/work blocks around fixed events.
"""Core scheduling logic — places flexible task blocks around fixed events."""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Tuple


@dataclass
class FixedEvent:
    start: datetime
    end: datetime


@dataclass
class Task:
    id: str
    title: str
    due_date: datetime
    estimated_minutes: int


@dataclass
class ScheduleBlock:
    id: str
    task_id: str
    task_title: str
    start: datetime
    end: datetime


def _merge_intervals(intervals: List[Tuple[datetime, datetime]]) -> List[Tuple[datetime, datetime]]:
    if not intervals:
        return []
    ordered = sorted(intervals, key=lambda x: x[0])
    merged: List[Tuple[datetime, datetime]] = [ordered[0]]
    for start, end in ordered[1:]:
        ps, pe = merged[-1]
        if start <= pe:
            merged[-1] = (ps, max(pe, end))
        else:
            merged.append((start, end))
    return merged


def _first_gap_slot(
    busy_merged: List[Tuple[datetime, datetime]],
    duration: timedelta,
    gap_start: datetime,
    deadline: datetime,
) -> Tuple[datetime, datetime] | None:
    """Earliest [s, s + duration) with s >= gap_start and end <= deadline, avoiding busy."""
    if gap_start + duration > deadline:
        return None
    prev_end = gap_start
    i = 0
    n = len(busy_merged)
    while prev_end + duration <= deadline:
        while i < n and busy_merged[i][1] <= prev_end:
            i += 1
        next_busy_start = busy_merged[i][0] if i < n else deadline
        free_cap = min(next_busy_start, deadline)
        if prev_end + duration <= free_cap:
            return (prev_end, prev_end + duration)
        if i < n:
            prev_end = max(prev_end, busy_merged[i][1])
            i += 1
        else:
            break
    return None


class SchedulerService:
    def suggest_blocks(
        self,
        tasks: List[Task],
        fixed_events: List[FixedEvent],
        look_ahead_days: int = 7,
        *,
        window_start: datetime | None = None,
    ) -> List[ScheduleBlock]:
        """
        Suggest study/work blocks for each task, avoiding conflicts with fixed events.
        Tasks are sorted by due date (soonest first). Greedy: first fit in free gaps.
        """
        if not tasks:
            return []

        window_start = window_start or datetime.now().replace(microsecond=0)
        horizon_end = window_start + timedelta(days=look_ahead_days)

        busy: List[Tuple[datetime, datetime]] = []
        for fe in fixed_events:
            s = max(fe.start, window_start)
            e = min(fe.end, horizon_end)
            if s < e:
                busy.append((s, e))
        busy = _merge_intervals(busy)

        blocks: List[ScheduleBlock] = []
        for task in sorted(tasks, key=lambda t: t.due_date):
            duration = timedelta(minutes=max(1, task.estimated_minutes))
            deadline = min(task.due_date, horizon_end)
            if deadline <= window_start:
                continue
            slot = _first_gap_slot(busy, duration, window_start, deadline)
            if slot is None:
                continue
            start, end = slot
            if end > task.due_date:
                continue
            blocks.append(
                ScheduleBlock(
                    id=str(uuid.uuid4()),
                    task_id=task.id,
                    task_title=task.title,
                    start=start,
                    end=end,
                )
            )
            busy.append((start, end))
            busy = _merge_intervals(busy)

        return blocks

    def suggest_task_sessions(
        self,
        task: Task,
        fixed_events: List[FixedEvent],
        look_ahead_days: int = 7,
        *,
        window_start: datetime | None = None,
        max_block_minutes: int = 90,
    ) -> List[ScheduleBlock]:
        """Place one task as proportional study sessions sized by estimated_minutes."""
        window_start = window_start or datetime.now().replace(microsecond=0)
        horizon_end = window_start + timedelta(days=look_ahead_days)
        deadline = min(task.due_date, horizon_end)
        if deadline <= window_start:
            return []

        total = max(15, task.estimated_minutes)
        chunks = _split_work_minutes(total, max_block=max_block_minutes)
        busy: List[Tuple[datetime, datetime]] = []
        for fe in fixed_events:
            s = max(fe.start, window_start)
            e = min(fe.end, horizon_end)
            if s < e:
                busy.append((s, e))
        busy = _merge_intervals(busy)

        blocks: List[ScheduleBlock] = []
        session_count = len(chunks)
        for idx, minutes in enumerate(chunks):
            duration = timedelta(minutes=minutes)
            slot = _first_gap_slot(busy, duration, window_start, deadline)
            if slot is None:
                continue
            start, end = slot
            title = task.title
            if session_count > 1:
                title = f"{task.title} ({idx + 1}/{session_count})"
            blocks.append(
                ScheduleBlock(
                    id=str(uuid.uuid4()),
                    task_id=task.id,
                    task_title=title,
                    start=start,
                    end=end,
                )
            )
            busy.append((start, end))
            busy = _merge_intervals(busy)
        return blocks


def _split_work_minutes(total: int, *, max_block: int = 90, min_block: int = 30) -> List[int]:
    """Split total work into session lengths (e.g. 180 min → 90 + 90)."""
    total = max(min_block, total)
    if total <= max_block:
        return [total]
    chunks: List[int] = []
    remaining = total
    while remaining > 0:
        if remaining <= max_block:
            chunks.append(remaining)
            break
        chunk = max_block
        if remaining - chunk < min_block:
            chunk = remaining - min_block
        chunks.append(chunk)
        remaining -= chunk
    return chunks or [min_block]
