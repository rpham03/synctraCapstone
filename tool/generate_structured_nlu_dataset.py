#!/usr/bin/env python3
"""Generate Syntra's shared 1,000-example structured NLU dataset."""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import Counter
from itertools import product
from pathlib import Path
from typing import Any, Iterable


DEFAULT_DATASET_SIZE = 1000
DEFAULT_SEED = 13
TRAIN_RATIO = 0.70
TEST_RATIO = 0.30
TOOLS = [
    "get_assignments",
    "find_free_slots",
    "get_calendar_events",
    "get_tasks",
    "propose_schedule_change",
    "add_calendar_block",
    "delete_calendar_block",
    "ai_agent",
]
INTENTS = {
    "get_assignments": "sync_assignments",
    "find_free_slots": "find_availability",
    "get_calendar_events": "list_calendar_events",
    "get_tasks": "list_tasks",
    "propose_schedule_change": "propose_study_schedule",
    "add_calendar_block": "create_calendar_event",
    "delete_calendar_block": "delete_calendar_event",
    "ai_agent": "general_assistance",
}


def example(
    user_message: str,
    tool: str,
    *,
    slots: dict[str, str] | None = None,
    missing_slots: Iterable[str] = (),
    followup_question: str | None = None,
) -> dict[str, Any]:
    missing = list(missing_slots)
    return {
        "user_message": user_message,
        "intent": INTENTS[tool],
        "tool": tool,
        "slots": slots or {},
        "needs_followup": bool(missing),
        "missing_slots": missing,
        "followup_question": followup_question if missing else None,
    }


def _base_examples() -> list[dict[str, Any]]:
    return [
        example(
            "Study for CSE 369 Thursday from 7 PM to 9 PM",
            "add_calendar_block",
            slots={
                "title": "Study for CSE 369",
                "date": "Thursday",
                "start_time": "7 PM",
                "end_time": "9 PM",
            },
        ),
        example(
            "Add a calendar block tomorrow",
            "add_calendar_block",
            slots={"date": "tomorrow"},
            missing_slots=("title", "start_time", "end_time"),
            followup_question="What event name, start time, and end time should I use?",
        ),
        example(
            "Add a calendar block tomorrow from 2 PM to 3 PM",
            "add_calendar_block",
            slots={"date": "tomorrow", "start_time": "2 PM", "end_time": "3 PM"},
            missing_slots=("title",),
            followup_question="What event name should I use?",
        ),
        example(
            "Delete my Bible study",
            "delete_calendar_block",
            slots={"title": "Bible study"},
        ),
        example(
            "Remove Bible study and dentist tomorrow",
            "delete_calendar_block",
            slots={"title": "Bible study and dentist", "date": "tomorrow"},
        ),
        example(
            "Delete an event",
            "delete_calendar_block",
            missing_slots=("title",),
            followup_question="Which event should I remove?",
        ),
        example(
            "Plan today",
            "add_calendar_block",
            slots={"date": "today"},
            missing_slots=("title", "start_time", "end_time"),
            followup_question="What event name, start time, and end time should I use?",
        ),
        example(
            "What homework is due tomorrow?",
            "get_tasks",
            slots={"date": "tomorrow"},
        ),
        example(
            "Show CSE 369 assignments due Friday",
            "get_tasks",
            slots={"course": "CSE 369", "date": "Friday"},
        ),
        example(
            "What is on my calendar today?",
            "get_calendar_events",
            slots={"date": "today"},
        ),
        example(
            "Schedule 2 hours for lab 7 by Friday",
            "propose_schedule_change",
            slots={"title": "lab 7", "duration": "2 hours", "deadline": "Friday"},
        ),
        example(
            "Schedule time for my assignment",
            "propose_schedule_change",
            slots={"title": "my assignment"},
            missing_slots=("duration", "deadline"),
            followup_question="How much time do you need, and what is the deadline?",
        ),
        example("Check Canvas for new assignments", "get_assignments"),
        example(
            "When am I free tomorrow?",
            "find_free_slots",
            slots={"date": "tomorrow"},
        ),
        example("Write an email to my professor", "ai_agent"),
    ]


def _candidate_examples() -> dict[str, list[dict[str, Any]]]:
    pools = {tool: [] for tool in TOOLS}
    courses = [
        "CSE 369",
        "calculus",
        "biology",
        "chemistry",
        "physics",
        "history",
        "statistics",
        "economics",
        "algorithms",
        "psychology",
    ]
    dates = [
        "today",
        "tomorrow",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "Friday",
        "Saturday",
        "Sunday",
        "this week",
        "next week",
        "this weekend",
    ]
    work_items = [
        "lab report",
        "essay draft",
        "problem set",
        "project proposal",
        "reading response",
        "discussion post",
        "quiz review",
        "final paper",
        "coding exercise",
        "presentation",
    ]
    durations = ["30 minutes", "45 minutes", "1 hour", "90 minutes", "2 hours"]
    ranges = [
        ("8 AM", "9 AM"),
        ("9 AM", "10:30 AM"),
        ("11 AM", "12 PM"),
        ("1 PM", "2 PM"),
        ("2 PM", "3:30 PM"),
        ("4 PM", "5 PM"),
        ("6 PM", "7 PM"),
        ("7 PM", "9 PM"),
    ]

    assignment_templates = [
        "Check Canvas for new {course} assignments",
        "Pull the latest {course} homework from Canvas",
        "Refresh {course} work from the LMS",
        "Sync posted {course} deadlines from the course portal",
        "See whether the {course} course site posted anything new",
    ]
    for course, template in product(courses, assignment_templates):
        pools["get_assignments"].append(
            example(template.format(course=course), "get_assignments", slots={"course": course})
        )
    for course, date_value in product(courses, dates):
        pools["get_assignments"].append(
            example(
                f"Check Canvas for {course} work posted {date_value}",
                "get_assignments",
                slots={"course": course, "date": date_value},
            )
        )
    for item, template in product(
        work_items,
        [
            "Load {item} details from Canvas",
            "Sync the {item} from my course portal",
            "Check whether the LMS posted the {item}",
            "Pull the newest {item} instructions from Canvas",
        ],
    ):
        pools["get_assignments"].append(
            example(template.format(item=item), "get_assignments", slots={"title": item})
        )

    free_templates = [
        "When am I free {date}?",
        "Find open time {date}",
        "Show my availability {date}",
        "Where is there a gap in my calendar {date}?",
    ]
    for date_value, template in product(dates, free_templates):
        pools["find_free_slots"].append(
            example(
                template.format(date=date_value),
                "find_free_slots",
                slots={"date": date_value},
            )
        )
    for course, date_value in product(courses, dates):
        pools["find_free_slots"].append(
            example(
                f"When can I study {course} {date_value}?",
                "find_free_slots",
                slots={"course": course, "date": date_value},
            )
        )
    for duration, date_value in product(durations, dates):
        pools["find_free_slots"].append(
            example(
                f"Find {duration} of free time {date_value}",
                "find_free_slots",
                slots={"duration": duration, "date": date_value},
            )
        )

    for course, date_value, template in product(
        courses,
        dates,
        [
            "Show my {course} calendar {date}",
            "Do I have {course} class {date}?",
            "When is my {course} meeting {date}?",
        ],
    ):
        pools["get_calendar_events"].append(
            example(
                template.format(course=course, date=date_value),
                "get_calendar_events",
                slots={"course": course, "date": date_value},
            )
        )
    for date_value in dates:
        pools["get_calendar_events"].append(
            example(
                f"What events are on my calendar {date_value}?",
                "get_calendar_events",
                slots={"date": date_value},
            )
        )

    for course, date_value, template in product(
        courses,
        dates,
        [
            "What {course} homework is due {date}?",
            "Show {course} deadlines for {date}",
            "What do I need to submit for {course} {date}?",
        ],
    ):
        pools["get_tasks"].append(
            example(
                template.format(course=course, date=date_value),
                "get_tasks",
                slots={"course": course, "date": date_value},
            )
        )
    for item, date_value in product(work_items, dates):
        pools["get_tasks"].append(
            example(
                f"Is the {item} due {date_value}?",
                "get_tasks",
                slots={"title": item, "date": date_value},
            )
        )

    for item, duration, deadline in product(work_items, durations, dates):
        pools["propose_schedule_change"].append(
            example(
                f"Schedule {duration} for {item} by {deadline}",
                "propose_schedule_change",
                slots={"title": item, "duration": duration, "deadline": deadline},
            )
        )
    for item, deadline in product(work_items, dates):
        pools["propose_schedule_change"].append(
            example(
                f"Schedule time for {item} by {deadline}",
                "propose_schedule_change",
                slots={"title": item, "deadline": deadline},
                missing_slots=("duration",),
                followup_question="How much time should I schedule?",
            )
        )
    for item, duration in product(work_items, durations):
        pools["propose_schedule_change"].append(
            example(
                f"Plan {duration} for {item}",
                "propose_schedule_change",
                slots={"title": item, "duration": duration},
                missing_slots=("deadline",),
                followup_question="What is the deadline?",
            )
        )

    calendar_titles = [
        "Study for CSE 369",
        "calculus review",
        "biology lab prep",
        "project meeting",
        "office hours",
        "essay writing",
        "group study",
        "advisor appointment",
        "coding practice",
        "exam review",
    ]
    calendar_templates = [
        "Add {title} {date} from {start} to {end}",
        "{title} {date} from {start} until {end}",
        "Could you put {title} on my calendar for {date} between {start} and {end}?",
        "I need {title} {date} starting at {start} and ending at {end}",
        "{date}, please add {title} between {start} and {end}",
        "Book {title} on {date}, {start} through {end}",
        "Please create {title} for {date} with a start time of {start} and end time of {end}",
    ]
    for title, date_value, time_range, template in product(
        calendar_titles,
        dates[:9],
        ranges,
        calendar_templates,
    ):
        start_time, end_time = time_range
        pools["add_calendar_block"].append(
            example(
                template.format(
                    title=title,
                    date=date_value,
                    start=start_time,
                    end=end_time,
                ),
                "add_calendar_block",
                slots={
                    "title": title,
                    "date": date_value,
                    "start_time": start_time,
                    "end_time": end_time,
                },
            )
        )
    for date_value in dates:
        pools["add_calendar_block"].append(
            example(
                f"Add a calendar block {date_value}",
                "add_calendar_block",
                slots={"date": date_value},
                missing_slots=("title", "start_time", "end_time"),
                followup_question="What event name, start time, and end time should I use?",
            )
        )
        pools["add_calendar_block"].append(
            example(
                f"Plan {date_value}",
                "add_calendar_block",
                slots={"date": date_value},
                missing_slots=("title", "start_time", "end_time"),
                followup_question="What event name, start time, and end time should I use?",
            )
        )
    for date_value, time_range in product(dates, ranges):
        start_time, end_time = time_range
        pools["add_calendar_block"].append(
            example(
                f"Add a calendar block {date_value} from {start_time} to {end_time}",
                "add_calendar_block",
                slots={"date": date_value, "start_time": start_time, "end_time": end_time},
                missing_slots=("title",),
                followup_question="What event name should I use?",
            )
        )

    delete_templates = [
        "Delete my {title} {date}",
        "Remove the {title} from my calendar {date}",
        "Cancel {title} on {date}",
        "Take {title} off my calendar {date}",
        "Get rid of {title} from my schedule {date}",
        "Erase {title} {date}",
        "Drop {title} from the calendar {date}",
    ]
    for title, date_value, template in product(
        calendar_titles,
        dates[:9],
        delete_templates,
    ):
        pools["delete_calendar_block"].append(
            example(
                template.format(title=title, date=date_value),
                "delete_calendar_block",
                slots={"title": title, "date": date_value},
            )
        )
    for first, second, date_value in product(
        calendar_titles[:6],
        calendar_titles[6:],
        dates[:9],
    ):
        combined = f"{first} and {second}"
        pools["delete_calendar_block"].append(
            example(
                f"Cancel both {combined} {date_value}",
                "delete_calendar_block",
                slots={"title": combined, "date": date_value},
            )
        )
    for date_value in dates:
        pools["delete_calendar_block"].append(
            example(
                f"Clear every event from my calendar {date_value}",
                "delete_calendar_block",
                slots={"date": date_value},
            )
        )
        pools["delete_calendar_block"].append(
            example(
                f"Remove all study blocks {date_value}",
                "delete_calendar_block",
                slots={"title": "study blocks", "date": date_value},
            )
        )
    for message in (
        "Delete an event",
        "Remove something from my calendar",
        "Cancel a calendar block",
        "Take an appointment off my schedule",
    ):
        pools["delete_calendar_block"].append(
            example(
                message,
                "delete_calendar_block",
                missing_slots=("title",),
                followup_question="Which event should I remove?",
            )
        )

    general_actions = [
        "write an email to my professor",
        "explain recursion",
        "summarize these notes",
        "rewrite this paragraph",
        "brainstorm ideas for my capstone",
        "proofread my message",
        "translate this sentence into Spanish",
        "help me debug my Python code",
        "explain big O notation",
        "make a checklist for finals",
        "give me study tips",
        "help me understand this syllabus policy",
        "draft an apology email",
        "explain photosynthesis",
        "help me outline my essay",
        "make this sentence more professional",
        "explain this error message",
        "give me presentation topic ideas",
        "tell me a joke",
        "help me feel less stressed",
        "explain machine learning",
        "write a polite reply to my teammate",
        "help me prepare interview questions",
        "convert this paragraph into bullet points",
        "help me choose a research topic",
        "explain this assignment prompt",
        "write a thank you note",
        "help me practice for a presentation",
        "suggest ways to improve my focus",
    ]
    prefixes = ["", "Can you ", "Please ", "I need help to ", "Help me "]
    for action, prefix in product(general_actions, prefixes):
        message = f"{prefix}{action}"
        pools["ai_agent"].append(example(message[0].upper() + message[1:], "ai_agent"))
    for greeting in [
        "Hi",
        "Hello",
        "Good morning",
        "How are you?",
        "Thanks for your help",
        "What can you do?",
        "I feel stressed",
        "I need advice",
        "When is summer?",
        "What is the capital of France?",
    ]:
        pools["ai_agent"].append(example(greeting, "ai_agent"))

    return pools


def build_structured_examples(
    target_size: int = DEFAULT_DATASET_SIZE,
    seed: int = DEFAULT_SEED,
) -> list[dict[str, Any]]:
    if target_size < len(TOOLS):
        raise ValueError(f"target_size must be at least {len(TOOLS)}")

    by_tool = {tool: [] for tool in TOOLS}
    seen: set[str] = set()

    def add(row: dict[str, Any]) -> None:
        key = " ".join(row["user_message"].lower().split())
        if key in seen:
            return
        seen.add(key)
        by_tool[row["tool"]].append(row)

    for row in _base_examples():
        add(row)

    rng = random.Random(seed)
    pools = _candidate_examples()
    for tool in TOOLS:
        rng.shuffle(pools[tool])

    base_count, remainder = divmod(target_size, len(TOOLS))
    targets = {
        tool: base_count + (1 if index < remainder else 0)
        for index, tool in enumerate(TOOLS)
    }
    for tool in TOOLS:
        for row in pools[tool]:
            if len(by_tool[tool]) >= targets[tool]:
                break
            add(row)
        if len(by_tool[tool]) != targets[tool]:
            raise ValueError(
                f"Could only generate {len(by_tool[tool])} unique {tool} examples; "
                f"expected {targets[tool]}"
            )

    rows = [row for tool in TOOLS for row in by_tool[tool]]
    rng.shuffle(rows)
    validate_examples(rows, target_size=target_size)
    return rows


def validate_examples(rows: list[dict[str, Any]], *, target_size: int) -> None:
    if len(rows) != target_size:
        raise ValueError(f"Dataset has {len(rows)} rows; expected {target_size}")
    messages = [" ".join(row["user_message"].lower().split()) for row in rows]
    if len(set(messages)) != len(messages):
        raise ValueError("Dataset contains duplicate user_message values")
    counts = Counter(row["tool"] for row in rows)
    if set(counts) != set(TOOLS):
        raise ValueError(f"Dataset tool labels do not match expected tools: {counts}")
    if max(counts.values()) - min(counts.values()) > 1:
        raise ValueError(f"Dataset is not balanced across tools: {counts}")


def balanced_split_indices(
    labels: list[str],
    *,
    train_ratio: float = TRAIN_RATIO,
    seed: int = DEFAULT_SEED,
) -> tuple[list[int], list[int]]:
    """Return deterministic, label-balanced train and test row indices."""

    if not 0 < train_ratio < 1:
        raise ValueError("train_ratio must be between 0 and 1")
    by_label: dict[str, list[int]] = {}
    for index, label in enumerate(labels):
        by_label.setdefault(label, []).append(index)

    desired_train_total = int(round(len(labels) * train_ratio))
    raw_targets = {
        label: len(indices) * train_ratio for label, indices in by_label.items()
    }
    train_targets = {
        label: math.floor(raw_target) for label, raw_target in raw_targets.items()
    }
    remaining = desired_train_total - sum(train_targets.values())
    label_order = {label: index for index, label in enumerate(TOOLS)}
    ranked_labels = sorted(
        by_label,
        key=lambda label: (
            -(raw_targets[label] - train_targets[label]),
            label_order.get(label, len(TOOLS)),
            label,
        ),
    )
    for label in ranked_labels[:remaining]:
        train_targets[label] += 1

    rng = random.Random(seed)
    train_indices: list[int] = []
    test_indices: list[int] = []
    for label, indices in by_label.items():
        shuffled = list(indices)
        rng.shuffle(shuffled)
        split_at = train_targets[label]
        train_indices.extend(shuffled[:split_at])
        test_indices.extend(shuffled[split_at:])
    rng.shuffle(train_indices)
    rng.shuffle(test_indices)
    return train_indices, test_indices


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(Path(__file__).with_name("syntra_nlu_training_data.jsonl")),
    )
    parser.add_argument("--size", type=int, default=DEFAULT_DATASET_SIZE)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    dataset = build_structured_examples(args.size, args.seed)
    write_jsonl(Path(args.output), dataset)
    counts = Counter(row["tool"] for row in dataset)
    train_indices, test_indices = balanced_split_indices(
        [row["tool"] for row in dataset],
        seed=args.seed,
    )
    print(
        json.dumps(
            {
                "output": args.output,
                "total_examples": len(dataset),
                "train_examples": len(train_indices),
                "test_examples": len(test_indices),
                "label_counts": counts,
            },
            indent=2,
        )
    )
