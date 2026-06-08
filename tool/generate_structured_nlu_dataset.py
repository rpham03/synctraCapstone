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


DEFAULT_DATASET_SIZE = 5000
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
    "move_calendar_block",
    "delete_calendar_block",
    "set_productivity_preferences",
    "get_productivity_preferences",
    "remove_productivity_preferences",
    "classify_all_calendar_events",
    "classify_calendar_item",
    "set_event_flexibility_override",
    "suggest_preference_schedule",
    "apply_preference_schedule",
    "ai_agent",
]
INTENTS = {
    "get_assignments": "sync_assignments",
    "find_free_slots": "find_availability",
    "get_calendar_events": "list_calendar_events",
    "get_tasks": "list_tasks",
    "propose_schedule_change": "propose_study_schedule",
    "add_calendar_block": "create_calendar_event",
    "move_calendar_block": "move_calendar_event",
    "delete_calendar_block": "delete_calendar_event",
    "set_productivity_preferences": "set_productive_period",
    "get_productivity_preferences": "get_productive_period",
    "remove_productivity_preferences": "remove_productive_period",
    "classify_all_calendar_events": "classify_calendar",
    "classify_calendar_item": "classify_event",
    "set_event_flexibility_override": "override_event_flexibility",
    "suggest_preference_schedule": "suggest_schedule",
    "apply_preference_schedule": "apply_schedule",
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

    _add_feature_pools(pools)
    return pools


def _cap(message: str) -> str:
    return message[0].upper() + message[1:] if message else message


def _add_feature_pools(pools: dict[str, list[dict[str, Any]]]) -> None:
    """Move, productivity-preference, classification, and scheduling examples."""

    titles = [
        "study block", "bible study", "gaming", "workout", "meeting", "dentist",
        "lab 7", "reading", "group study", "office hours", "piano practice",
        "review session", "standup", "project work", "CSE 369 review", "book club",
    ]
    days = [
        "today", "tomorrow", "Monday", "Tuesday", "Wednesday", "Thursday",
        "Friday", "Saturday", "Sunday", "this weekend", "next week",
    ]
    times = ["9 AM", "10 AM", "1 PM", "2 PM", "3 PM", "5 PM", "7 PM", "8 PM", "9 PM"]

    # ---- move_calendar_block ----
    for verb, title, day in product(["Move", "Reschedule", "Shift"], titles, days):
        pools["move_calendar_block"].append(
            example(f"{verb} my {title} to {day}", "move_calendar_block",
                    slots={"title": title, "date": day})
        )
    for title, day, t in product(titles, ["Friday", "Monday", "tomorrow", "Saturday"], times):
        pools["move_calendar_block"].append(
            example(f"Move my {title} to {day} at {t}", "move_calendar_block",
                    slots={"title": title, "date": day, "start_time": t})
        )
    for title, (t1, t2) in product(
        titles, [("2 PM", "7 PM"), ("9 AM", "11 AM"), ("1 PM", "4 PM"), ("8 PM", "9 PM")]
    ):
        pools["move_calendar_block"].append(
            example(f"Move my {title} from {t1} to {t2}", "move_calendar_block",
                    slots={"title": title, "start_time": t1, "end_time": t2})
        )
    for verb, title, dur in product(
        ["Extend", "Shorten", "Lengthen"], titles, ["1 hour", "2 hours", "30 minutes"]
    ):
        pools["move_calendar_block"].append(
            example(f"{verb} my {title} by {dur}", "move_calendar_block")
        )

    # ---- set_productivity_preferences ----
    periods = ["morning", "afternoon", "evening", "night"]
    set_templates = [
        "I'm productive in the {p}", "I work best in the {p}",
        "I focus best in the {p}", "I'm most productive in the {p}",
        "I do my best work in the {p}", "I get the most done in the {p}",
        "I'm sharpest in the {p}", "I concentrate best in the {p}",
        "I have the most energy in the {p}", "I prefer to work in the {p}",
        "I like working in the {p}", "{p} is when I'm most productive",
        "I'm at my best in the {p}", "set my productive time to the {p}",
        "save the {p} as my productive time", "I'm a {p} person",
        "my most productive time is the {p}", "I do focused work in the {p}",
        "I study best in the {p}", "I'm productive during the {p}",
        "I tend to focus in the {p}", "the {p} is my productive window",
        "I usually work best in the {p}", "I'm most alert in the {p}",
        "I get my best work done in the {p}",
    ]
    for tmpl, p in product(set_templates, periods):
        pools["set_productivity_preferences"].append(
            example(_cap(tmpl.format(p=p)), "set_productivity_preferences")
        )
    pairs = [("morning", "night"), ("morning", "evening"), ("afternoon", "evening"),
             ("morning", "afternoon"), ("evening", "night"), ("afternoon", "night")]
    pair_templates = [
        "I'm productive in the {a} and at {b}", "I work best in the {a} and {b}",
        "I'm most productive in the {a} and the {b}", "I focus in the {a} and the {b}",
        "I do my best work in the {a} and {b}", "my productive times are {a} and {b}",
    ]
    for tmpl, (a, b) in product(pair_templates, pairs):
        pools["set_productivity_preferences"].append(
            example(_cap(tmpl.format(a=a, b=b)), "set_productivity_preferences")
        )
    tr = [("8 PM", "11 PM"), ("6 AM", "9 AM"), ("9 PM", "12 AM"), ("1 PM", "4 PM"),
          ("7 AM", "10 AM"), ("8 AM", "11 AM"), ("6 PM", "9 PM"), ("5 PM", "8 PM"),
          ("2 PM", "5 PM"), ("10 AM", "1 PM")]
    tr_templates = [
        "I'm productive from {t1} to {t2}", "I work best from {t1} to {t2}",
        "my productive hours are {t1} to {t2}", "I do my best work from {t1} to {t2}",
        "set my productive time to {t1} to {t2}",
    ]
    for tmpl, (t1, t2) in product(tr_templates, tr):
        pools["set_productivity_preferences"].append(
            example(_cap(tmpl.format(t1=t1, t2=t2)), "set_productivity_preferences",
                    slots={"start_time": t1, "end_time": t2})
        )

    # ---- get_productivity_preferences ----
    pref_nouns = [
        "productivity preferences", "productive times", "productive periods",
        "preferred work hours", "focus times", "productive hours",
        "preferred productive times", "productivity settings",
    ]
    for lead, noun, tail in product(
        ["What are", "Show me", "Tell me", "Remind me of", "List", "Get",
         "Can you list", "What did I set for", "Do you remember", "Look up"],
        pref_nouns,
        ["", "?", " please"],
    ):
        pools["get_productivity_preferences"].append(
            example(f"{lead} my {noun}{tail}".strip(), "get_productivity_preferences")
        )

    # ---- remove_productivity_preferences ----
    rm_verbs = ["Remove", "Clear", "Delete", "Forget", "Reset", "Drop"]
    for verb, noun, tail in product(rm_verbs, pref_nouns, ["", " now"]):
        pools["remove_productivity_preferences"].append(
            example(f"{verb} my {noun}{tail}".strip(), "remove_productivity_preferences")
        )
    for verb, p, tmpl in product(
        rm_verbs, periods,
        ["my {p} preference", "the {p} productive time", "{p} from my preferences",
         "my {p} productivity preference"],
    ):
        pools["remove_productivity_preferences"].append(
            example(f"{verb} {tmpl.format(p=p)}", "remove_productivity_preferences")
        )

    # ---- classify_all_calendar_events ----
    for v, s, suf in product(
        ["Classify", "Sort", "Label", "Categorize", "Organize", "Mark"],
        ["my calendar", "all my events", "everything on my calendar",
         "my whole calendar", "my schedule", "my events", "my week",
         "all my calendar events"],
        ["", "into fixed and flexible", "as fixed or flexible", "by type"],
    ):
        pools["classify_all_calendar_events"].append(
            example(f"{v} {s} {suf}".strip(), "classify_all_calendar_events")
        )
    for q in [
        "Which events are fixed or flexible", "What's fixed and what's flexible on my calendar",
        "Tell me which events are fixed or flexible", "Which of my events are flexible",
        "What on my calendar is fixed", "Go through my calendar and mark fixed or flexible",
    ]:
        pools["classify_all_calendar_events"].append(
            example(q, "classify_all_calendar_events")
        )

    # ---- classify_calendar_item ----
    item_templates = [
        "Is my {t} fixed or flexible", "Classify my {t}", "Is {t} fixed or flexible",
        "What is {t}, fixed or flexible", "Tell me if my {t} is fixed or flexible",
        "Is the {t} fixed or flexible", "Classify the {t} on my calendar",
        "Is my {t} a fixed event", "Would you classify my {t}",
        "Is {t} flexible or fixed", "Check if my {t} is fixed",
        "Decide if my {t} is fixed or flexible",
    ]
    for tmpl, t in product(item_templates, titles):
        pools["classify_calendar_item"].append(
            example(tmpl.format(t=t), "classify_calendar_item", slots={"title": t})
        )

    # ---- set_event_flexibility_override ----
    for v, t, fx in product(["Mark", "Set", "Treat", "Make"], titles, ["fixed", "flexible"]):
        pools["set_event_flexibility_override"].append(
            example(f"{v} my {t} as {fx}", "set_event_flexibility_override",
                    slots={"title": t})
        )
    for t, fx in product(titles, ["fixed", "flexible"]):
        pools["set_event_flexibility_override"].append(
            example(f"My {t} is {fx}", "set_event_flexibility_override", slots={"title": t})
        )
        pools["set_event_flexibility_override"].append(
            example(f"Treat the {t} as {fx}", "set_event_flexibility_override",
                    slots={"title": t})
        )

    # ---- suggest_preference_schedule ----
    for core, obj, lead in product(
        ["Suggest", "Plan", "Build", "Create", "Propose", "Put together", "Draft", "Arrange"],
        ["a schedule for my flexible work", "my flexible tasks",
         "a study schedule near my productive time", "blocks for my flexible events",
         "my week around my productive hours", "time for my flexible tasks",
         "a plan for my flexible work", "my flexible study blocks"],
        ["", "please ", "can you ", "could you "],
    ):
        pools["suggest_preference_schedule"].append(
            example(_cap(f"{lead}{core} {obj}".strip()), "suggest_preference_schedule")
        )

    # ---- apply_preference_schedule ----
    for core, obj, lead in product(
        ["Apply", "Confirm", "Lock in", "Save", "Add", "Accept", "Use", "Go ahead with"],
        ["the schedule", "those blocks", "that schedule", "the suggested times",
         "those study blocks", "the plan", "these times", "the suggested schedule"],
        ["", "yes ", "please ", "ok "],
    ):
        pools["apply_preference_schedule"].append(
            example(_cap(f"{lead}{core} {obj}".strip()), "apply_preference_schedule")
        )

    # ---- extra ai_agent variety (more tools now share the dataset) ----
    for action, lead in product(
        ["summarize this article", "explain recursion", "help me write a cover letter",
         "give me study tips", "motivate me to study", "explain this concept",
         "help me brainstorm a project", "proofread my essay", "translate this sentence",
         "recommend a good book", "tell me a fun fact", "help me relax",
         "explain the water cycle", "help me prepare for an interview",
         "help me outline an essay", "explain photosynthesis", "give me a pep talk",
         "help me word an email", "suggest a topic for my paper", "explain big-O notation",
         "help me make a study plan idea", "rewrite this more formally",
         "summarize these notes", "explain this error message",
         "help me with my resume", "explain this theorem", "give me motivation",
         "help me destress", "explain quantum computing", "suggest a workout",
         "help me journal", "explain the stock market", "give me a recipe",
         "help me set a goal", "explain machine learning", "suggest a podcast",
         "help me write a poem", "explain gravity", "tips for better sleep",
         "help me plan a trip", "explain inflation", "suggest a hobby",
         "help me focus better", "explain how DNA works"],
        ["", "Can you ", "Please ", "Could you "],
    ):
        pools["ai_agent"].append(example(_cap(f"{lead}{action}"), "ai_agent"))

    # ---- larger pools so the dataset can scale (e.g. 5,000 rows) ----
    titles2 = titles + [
        "calculus homework", "chemistry lab", "history reading", "team meeting",
        "therapy appointment", "club meeting", "volunteer shift", "language practice",
        "research session", "thesis writing", "coding practice", "art class",
    ]

    # get_assignments — Canvas-sync flavored.
    for lead, obj, tail in product(
        ["Check Canvas for", "Sync my", "Pull my", "Refresh my", "Fetch my",
         "Update my", "Get my", "Show me my", "Are there new", "List my",
         "Look up my", "Load my"],
        ["assignments", "Canvas assignments", "homework from Canvas", "new assignments",
         "assignment list", "Canvas homework", "upcoming assignments", "graded work"],
        ["", "?", " from Canvas"],
    ):
        pools["get_assignments"].append(
            example(f"{lead} {obj}{tail}".strip(), "get_assignments")
        )

    # find_free_slots — open-time questions with a date slot.
    for tmpl, d in product(
        ["When am I free {d}", "What free time do I have {d}", "When am I available {d}",
         "Show my open slots {d}", "Find free time {d}", "Where do I have gaps {d}",
         "When can I study {d}", "What's my availability {d}", "Do I have free time {d}",
         "When am I open {d}", "Find an open slot {d}", "What times am I free {d}"],
        ["today", "tomorrow", "this week", "Monday", "Tuesday", "Wednesday",
         "Thursday", "Friday", "this weekend", "next week"],
    ):
        pools["find_free_slots"].append(
            example(tmpl.format(d=d), "find_free_slots", slots={"date": d})
        )

    # set_productivity_preferences — more single-period phrasings.
    for tmpl, p in product(
        ["I'm productive mainly in the {p}", "I tend to do my best work in the {p}",
         "the {p} works best for me", "I'd rather work in the {p}",
         "I'm wired for the {p}", "I get a lot done in the {p}",
         "I think most clearly in the {p}", "I'm freshest in the {p}",
         "count me as a {p} worker", "my focus peaks in the {p}",
         "I'm productive especially in the {p}", "I have great focus in the {p}",
         "I work most efficiently in the {p}", "I'm energized in the {p}",
         "I prefer the {p} for deep work", "{p} works for my focus",
         "I really focus in the {p}", "the {p} is best for my studying",
         "I lock in during the {p}", "I'm dialed in during the {p}",
         "set my best work time to the {p}", "remember I'm productive in the {p}",
         "note that I work best in the {p}", "log my productive time as the {p}",
         "I'm a strong worker in the {p}", "I crush my work in the {p}",
         "my productivity peaks in the {p}", "I do deep work in the {p}",
         "I'm most disciplined in the {p}", "I'm at peak focus in the {p}"],
        periods,
    ):
        pools["set_productivity_preferences"].append(
            example(_cap(tmpl.format(p=p)), "set_productivity_preferences")
        )

    # get_productivity_preferences — extra nouns.
    for lead, noun, tail in product(
        ["What are", "Show me", "Tell me", "Remind me of", "List", "Get",
         "Can you list", "What did I set for", "Do you remember", "Look up"],
        ["preferred study times", "preferred focus times"],
        ["", "?", " please"],
    ):
        pools["get_productivity_preferences"].append(
            example(f"{lead} my {noun}{tail}".strip(), "get_productivity_preferences")
        )

    # remove_productivity_preferences — more phrasings.
    for verb, noun, tail in product(
        rm_verbs, pref_nouns, [" entirely", " for now", " from settings"],
    ):
        pools["remove_productivity_preferences"].append(
            example(f"{verb} my {noun}{tail}".strip(), "remove_productivity_preferences")
        )
    for verb, p in product(rm_verbs, periods):
        pools["remove_productivity_preferences"].append(
            example(f"I'm no longer productive in the {p}", "remove_productivity_preferences")
        )

    # classify_all_calendar_events — extra suffix variety.
    for v, s, suf in product(
        ["Classify", "Sort", "Label", "Categorize", "Organize", "Mark", "Tag", "Group"],
        ["my calendar", "all my events", "everything on my calendar",
         "my whole calendar", "my schedule", "my events", "my week",
         "all my calendar events"],
        ["right now", "for me", "today", "please"],
    ):
        pools["classify_all_calendar_events"].append(
            example(f"{v} {s} {suf}".strip(), "classify_all_calendar_events")
        )

    # classify_calendar_item — more titles.
    for tmpl, t in product(item_templates, titles2):
        pools["classify_calendar_item"].append(
            example(tmpl.format(t=t), "classify_calendar_item", slots={"title": t})
        )

    # set_event_flexibility_override — more titles and verbs.
    for v, t, fx in product(
        ["Mark", "Set", "Treat", "Make", "Tag", "Label"], titles2, ["fixed", "flexible"]
    ):
        pools["set_event_flexibility_override"].append(
            example(f"{v} my {t} as {fx}", "set_event_flexibility_override",
                    slots={"title": t})
        )

    # suggest_preference_schedule — more objects.
    for core, obj, lead in product(
        ["Suggest", "Plan", "Build", "Create", "Propose", "Put together", "Draft", "Arrange"],
        ["a schedule around my productive hours", "study time near my best hours",
         "my flexible work for the week", "blocks during my productive period",
         "a study plan near my focus time"],
        ["", "please ", "can you ", "could you "],
    ):
        pools["suggest_preference_schedule"].append(
            example(_cap(f"{lead}{core} {obj}".strip()), "suggest_preference_schedule")
        )

    # apply_preference_schedule — more objects.
    for core, obj, lead in product(
        ["Apply", "Confirm", "Lock in", "Save", "Add", "Accept", "Use", "Go ahead with"],
        ["the suggestion", "those suggested blocks", "the proposed schedule",
         "the proposed times", "that plan"],
        ["", "yes ", "please ", "ok "],
    ):
        pools["apply_preference_schedule"].append(
            example(_cap(f"{lead}{core} {obj}".strip()), "apply_preference_schedule")
        )


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
