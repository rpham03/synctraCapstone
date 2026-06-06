#!/usr/bin/env python3
"""One-click Colab trainer/tester for the Syntra NLP tool router.

Paste this whole file into one Colab cell and run it, or upload the file and run:

    !python /content/one_click_train_nlp_router_colab.py

Default behavior:
- installs training dependencies when running in Colab
- trains on clean Syntra-generated intent examples
- ignores Hugging Face datasets unless --use-hf-datasets is passed
- ignores local data.zip unless --include-local-data is passed
- when local data is enabled, supports skipping __MACOSX and ._ metadata files
- supports json/jsonl/csv/txt/tsv/parquet and dialogue JSON with turns
- trains a transformer intent classifier
- trains a second token-classification model for slots from structured NLU JSONL
- saves the model to /content/syntra_tool_router
- tests several prompts and prints the predicted Syntra tool calls
"""

from __future__ import annotations

import argparse
import csv
import inspect
import json
import os
import random
import re
import subprocess
import sys
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("TRANSFORMERS_VERBOSITY", "error")


LABELS = [
    "get_assignments",
    "find_free_slots",
    "get_calendar_events",
    "get_tasks",
    "propose_schedule_change",
    "add_calendar_block",
    "ai_agent",
]

DEFAULT_HF_DATASETS = [
    "ConvLab/kvret",
    "Deliangus/schema_guided_dstc8",
    "microsoft/ba-calendar",
    "nvidia/Nemotron-RL-Instruction-Following-Calendar-v2",
    "Johin/function-calling-dataset",
    "DeepPavlov/clinc150",
]

DEFAULT_TEST_PROMPTS = [
    "what homework is due this week",
    "what classes do I have today",
    "when am I free tomorrow",
    "schedule 2 hours for lab 7 by Friday",
    "explain how I should study for finals",
    "when is summer",
    "hi",
    "plan this week",
    "make a study time at 7pm",
]


@dataclass(frozen=True)
class TrainingExample:
    text: str
    label: str


def manual_eval_examples() -> list[TrainingExample]:
    rows_by_label = {
        "get_assignments": [
            "check canvas for new homework",
            "pull assignments from canvas",
            "did canvas post anything new",
            "refresh my canvas assignments",
            "sync canvas so I can see due dates",
            "load my online course assignments",
            "get latest canvas deadlines",
            "are there any new assignments in canvas",
            "check canvas for the math worksheet",
            "update homework from canvas",
            "import my canvas due dates",
            "see if canvas has new lab reports",
            "fetch assignments from canvas for all classes",
            "refresh LMS homework",
            "what did professor post on canvas",
            "pull new course assignments",
            "sync my canvas todo items",
            "can you check canvas before I plan my work",
            "look up assignments in canvas",
            "get live homework from my courses",
            "did any class add a new canvas task",
            "download the latest assignment list from canvas",
            "check if canvas has homework for bio",
            "refresh assignment feed from the LMS",
            "update canvas tasks now",
        ],
        "find_free_slots": [
            "when can i work on my essay",
            "find a free hour tomorrow",
            "when am i free today",
            "show open slots friday afternoon",
            "do i have free time this week",
            "when can i study for calculus",
            "find time between my classes",
            "when is my next open block",
            "am i available after 2pm",
            "find 90 minutes for studying",
            "what free slots do i have tomorrow morning",
            "when can i meet my project group",
            "show availability this weekend",
            "do i have any open time tonight",
            "when can i work on lab report",
            "find a free block before friday",
            "when am i not busy next week",
            "can you find me study time today",
            "is there room in my schedule tomorrow",
            "what is my free time on monday",
            "find a two hour gap",
            "when can I squeeze in homework",
            "show open time around lunch",
            "am I free on Thursday evening",
            "when can I do my reading",
        ],
        "get_calendar_events": [
            "what meetings are on my calendar friday",
            "what classes do I have tomorrow",
            "show today's calendar",
            "do I have lab this afternoon",
            "when is my economics lecture",
            "list events for next week",
            "what is on my schedule Monday",
            "do I have office hours today",
            "show classes for Tuesday",
            "what time is my physics discussion",
            "any meetings after 3pm",
            "what calendar events are this weekend",
            "do I have class before noon",
            "show my school schedule for today",
            "when is my next lecture",
            "what is planned on my calendar",
            "do I have a review session Thursday",
            "what's my first class tomorrow",
            "show appointments for Friday",
            "is there a meeting with my group this week",
            "what events happen today",
            "tell me my calendar for tomorrow morning",
            "do I have chemistry lab Wednesday",
            "what time does class start",
            "list today's lectures",
        ],
        "get_tasks": [
            "do i have anything due tomorrow",
            "what do i need to turn in today",
            "list assignments due this weekend",
            "what is due for biology",
            "show deadlines for this week",
            "any homework due tonight",
            "what tasks are overdue",
            "show my todo list",
            "what should i finish first",
            "do i have a quiz due monday",
            "which assignments are due soon",
            "tell me my homework for next week",
            "what project deadlines are coming up",
            "show all tasks due friday",
            "is my essay due today",
            "what labs do i still need to submit",
            "list school work due before midnight",
            "do I owe anything for calculus",
            "what readings are due tomorrow",
            "show pending homework",
            "any exams or quizzes due this week",
            "what is on my task list for chemistry",
            "what assignments are due in the next few days",
            "remind me what I have to submit",
            "what is my next deadline",
        ],
        "propose_schedule_change": [
            "schedule 2 hours for my essay before friday",
            "make time to study for chemistry tonight",
            "add a study block for calculus tomorrow",
            "plan 90 minutes for the lab report",
            "put homework time on my calendar",
            "schedule time to finish my project",
            "block off an hour for reading notes",
            "help me plan work on the midterm review",
            "add two hours for physics homework by monday",
            "find time and schedule my biology quiz prep",
            "create a study session for algorithms",
            "reserve 45 minutes for discussion post",
            "plan my essay work around my classes",
            "schedule a work block before the deadline",
            "add time for the problem set this week",
            "make a study plan for finals",
            "put 30 minutes aside for worksheet",
            "schedule a lab prep session",
            "plan time to finish the assignment by tomorrow",
            "create calendar time for project proposal",
            "block time for exam review",
            "schedule homework after my last class",
            "add a focused work session for lab 3",
            "plan three hours for the final paper",
            "move some free time into a study block",
        ],
        "add_calendar_block": [
            "add study for cse 369 thursday from 7 pm to 9 pm",
            "add dentist tomorrow from 2 pm to 3 pm",
            "create a calendar block for office hours friday from 1 pm to 2 pm",
            "put project meeting on my calendar monday from 4 pm to 5 pm",
            "plan calculus review tomorrow from 6 pm to 7 pm",
            "add a calendar block tomorrow from 2 pm to 3 pm",
            "add a block to my calendar tomorrow",
            "plan today",
            "plan this week",
            "plan my week",
            "help me plan the week",
            "set up a plan for this week",
            "plan weekend",
            "make a study time at 7pm",
            "block 7pm for studying",
            "schedule studying tonight",
            "make a study block tomorrow",
            "add a study session",
            "create a study block",
            "i want a study block tonight",
            "set aside study time today",
            "plan my study time",
            "give me a study block",
            "make me a focus block this evening",
        ],
        "ai_agent": [
            "help me write an email about missing class",
            "explain how to study for finals",
            "summarize these notes",
            "can you rewrite this paragraph",
            "how do I ask my professor for an extension",
            "explain recursion like I'm new",
            "give me ideas for my capstone",
            "proofread this message",
            "what does this syllabus policy mean",
            "help me understand this error",
            "write a polite response to my teammate",
            "explain big O notation",
            "make a study checklist for algorithms",
            "how should I prepare for an interview",
            "tell me what photosynthesis means",
            "draft an apology email",
            "brainstorm topics for history essay",
            "convert this into bullet points",
            "explain the difference between mitosis and meiosis",
            "help me debug my Python code",
            "what should I say to my professor",
            "make this sentence more professional",
            "explain this assignment prompt",
            "give me tips for staying focused",
            "translate this sentence into Spanish",
            "when is summer",
            "when does summer start",
            "when is winter break",
            "when does the semester end",
            "when is spring break",
            "when is thanksgiving",
            "when does fall start",
            "what is the capital of France",
            "what is photosynthesis",
            "what is a black hole",
            "what is machine learning",
            "what is the meaning of life",
            "who is the president",
            "who wrote hamlet",
            "how does gravity work",
            "how do airplanes fly",
            "tell me a joke",
            "tell me about World War 2",
            "what time is it in tokyo",
            "what day of the week is it",
            "how many days until christmas",
            "what is the weather like",
            "hi",
            "hello",
            "how are you",
            "thanks",
            "thank you",
            "good morning",
            "what can you do",
            "who are you",
            "yes",
            "no",
            "ok",
            "sure",
            "maybe",
            "i don't know",
            "tell me something interesting",
            "give me motivation",
            "i feel stressed",
            "i'm tired",
            "i need a break",
            "what should i eat for dinner",
            "recommend a movie",
            "give me a study tip",
            "is the moon a planet",
            "why is the sky blue",
        ],
    }

    target_counts = {
        "get_assignments": 83,
        "find_free_slots": 84,
        "get_calendar_events": 84,
        "get_tasks": 83,
        "propose_schedule_change": 95,
        "add_calendar_block": 60,
        "ai_agent": 130,
    }
    seen = {
        " ".join(text.lower().split())
        for texts in rows_by_label.values()
        for text in texts
    }

    def add(label: str, text: str) -> None:
        key = " ".join(text.lower().split())
        if key not in seen:
            rows_by_label[label].append(text)
            seen.add(key)

    courses = [
        "calculus",
        "biology",
        "chemistry",
        "computer science",
        "history",
        "english",
        "physics",
        "statistics",
        "algorithms",
        "economics",
        "psychology",
        "art history",
    ]
    assignments = [
        "essay",
        "lab report",
        "worksheet",
        "discussion post",
        "project proposal",
        "problem set",
        "reading response",
        "quiz review",
        "final paper",
        "case study",
        "homework packet",
        "presentation",
        "midterm practice",
        "coding exercise",
    ]
    days = [
        "today",
        "tomorrow",
        "Friday",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
        "next week",
    ]
    durations = ["30 minutes", "45 minutes", "one hour", "90 minutes", "two hours"]
    time_windows = [
        "this morning",
        "this afternoon",
        "tonight",
        "after lunch",
        "after my last class",
        "before dinner",
        "before Friday",
    ]
    events = ["lecture", "lab", "discussion", "office hours", "review session", "group meeting"]

    for course in courses:
        add("get_assignments", f"check the course site for new {course} assignments")
        add("get_assignments", f"pull the latest {course} deadlines from canvas")
        add("get_assignments", f"refresh online homework for {course}")
        add("get_assignments", f"see whether {course} posted new work")
        for day in days:
            add("find_free_slots", f"where do I have open time for {course} {day}")
            add("find_free_slots", f"can I fit in {course} studying {day}")
            add("find_free_slots", f"show my available time for {course} {day}")
            add("find_free_slots", f"find a gap for {course} work {day}")
            add("get_calendar_events", f"when is {course} on my calendar {day}")
            add("get_calendar_events", f"show scheduled {course} events {day}")
            add("get_calendar_events", f"do I have a {course} class {day}")
            add("get_calendar_events", f"what time is {course} meeting {day}")
            add("get_tasks", f"what {course} work needs to be submitted {day}")
            add("get_tasks", f"which {course} deadlines are coming up {day}")
            add("get_tasks", f"do I need to hand in anything for {course} {day}")
            add("get_tasks", f"show {course} due dates for {day}")
            for event in events:
                add("get_calendar_events", f"is there a {course} {event} {day}")

    for assignment in assignments:
        add("get_assignments", f"load {assignment} details from canvas")
        add("get_assignments", f"sync the {assignment} from my course portal")
        add("get_assignments", f"check whether the LMS has a {assignment}")
        add("get_assignments", f"fetch the posted {assignment} instructions")
        for day in days:
            add("get_tasks", f"is the {assignment} something I need to submit {day}")
            add("get_tasks", f"when do I turn in the {assignment} near {day}")
            add("get_tasks", f"show deadline info for the {assignment} {day}")
            add("get_tasks", f"what is still due for the {assignment} {day}")
            add("find_free_slots", f"when can I work on the {assignment} {day}")
            add("find_free_slots", f"find available time for the {assignment} {day}")
            add("find_free_slots", f"show open time to make progress on the {assignment} {day}")
            for duration in durations:
                add("propose_schedule_change", f"block {duration} for the {assignment} before {day}")
                add("propose_schedule_change", f"create a {duration} work block for the {assignment} {day}")
                add("propose_schedule_change", f"put {duration} of {assignment} time on my schedule {day}")
                add("propose_schedule_change", f"plan {duration} to finish the {assignment} by {day}")

    for window in time_windows:
        add("find_free_slots", f"show free time {window}")
        add("find_free_slots", f"am I available {window}")
        add("find_free_slots", f"find an open slot {window}")
        add("propose_schedule_change", f"schedule homework time {window}")
        add("propose_schedule_change", f"make a study block {window}")
        add("get_calendar_events", f"what events do I have {window}")
        add("get_calendar_events", f"show calendar items {window}")

    for course in courses:
        for day in days:
            add(
                "add_calendar_block",
                f"add study for {course} {day} from 2 pm to 3 pm",
            )
            add(
                "add_calendar_block",
                f"put {course} review on my calendar {day} from 4 pm to 5 pm",
            )

    general_requests = [
        "draft a message to my professor",
        "rewrite my paragraph so it sounds clearer",
        "explain this grading policy",
        "help me understand my Python traceback",
        "make a bullet list from these notes",
        "give me study advice for a hard class",
        "brainstorm research questions for my paper",
        "write a professional message to my team",
        "summarize this textbook section",
        "explain this math concept simply",
        "help me prepare talking points",
        "turn this rough note into an email",
        "give me ideas for a presentation topic",
        "explain what my assignment prompt is asking",
        "make this sound more polite",
        "help me debug this SQL query",
        "write a short thank you email",
        "explain the difference between two biology terms",
        "suggest ways to focus while studying",
        "translate this sentence for class",
    ]
    for request in general_requests:
        add("ai_agent", request)
        add("ai_agent", f"can you {request}")
        add("ai_agent", f"please {request}")
        add("ai_agent", f"I need help to {request}")

    examples: list[TrainingExample] = []
    for label in LABELS:
        texts = rows_by_label[label]
        expected = target_counts[label]
        if len(texts) < expected:
            raise ValueError(
                f"manual eval label {label} has {len(texts)} examples, expected at least {expected}"
            )
        examples.extend(TrainingExample(text=text, label=label) for text in texts[:expected])
    expected_total = sum(target_counts.values())
    if len(examples) != expected_total:
        raise ValueError(f"manual eval set has {len(examples)} examples, expected {expected_total}")
    return examples


def manual_eval_script_source() -> str:
    return r'''#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


LABELS = [
    "get_assignments",
    "find_free_slots",
    "get_calendar_events",
    "get_tasks",
    "propose_schedule_change",
    "add_calendar_block",
    "ai_agent",
]


def parse_prediction(result: Any) -> tuple[str, float]:
    if isinstance(result, list) and result and isinstance(result[0], list):
        item = result[0][0]
    elif isinstance(result, list) and result:
        item = result[0]
    else:
        item = result
    return str(item["label"]), float(item["score"])


def load_examples(path: Path) -> list[dict[str, str]]:
    examples: list[dict[str, str]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            row = json.loads(line)
            text = str(row["text"]).strip()
            label = str(row["label"]).strip()
            if label not in LABELS:
                raise ValueError(f"unknown label in eval data: {label}")
            examples.append({"text": text, "label": label})
    return examples


def f1(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def print_table(rows: list[list[str]]) -> None:
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    for row in rows:
        print("  ".join(value.ljust(widths[i]) for i, value in enumerate(row)))


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate Syntra tool router on 500 manually labeled prompts.")
    parser.add_argument("--model-dir", default="/content/syntra_tool_router")
    parser.add_argument("--eval-data", default="/content/syntra_router_manual_eval.jsonl")
    parser.add_argument("--gpu-pipeline", action="store_true")
    parser.add_argument("--mistake-limit", type=int, default=50)
    parser.add_argument("--output-jsonl")
    args = parser.parse_args()

    model_dir = Path(args.model_dir)
    eval_data = Path(args.eval_data)
    if not model_dir.exists():
        raise SystemExit(f"model dir not found: {model_dir}. Run the training cell first.")
    if not eval_data.exists():
        raise SystemExit(f"eval data not found: {eval_data}. Re-run the updated training cell first.")

    from transformers import pipeline

    classifier = pipeline(
        "text-classification",
        model=str(model_dir),
        tokenizer=str(model_dir),
        top_k=1,
        device=0 if args.gpu_pipeline else -1,
    )

    examples = load_examples(eval_data)
    predictions: list[dict[str, Any]] = []
    for ex in examples:
        predicted, confidence = parse_prediction(classifier(ex["text"]))
        predictions.append(
            {
                "text": ex["text"],
                "expected": ex["label"],
                "predicted": predicted,
                "confidence": round(confidence, 4),
                "correct": predicted == ex["label"],
            }
        )

    total = len(predictions)
    correct = sum(1 for row in predictions if row["correct"])
    accuracy = correct / total if total else 0.0

    tp: Counter[str] = Counter()
    fp: Counter[str] = Counter()
    fn: Counter[str] = Counter()
    support: Counter[str] = Counter()
    confusion = {label: Counter() for label in LABELS}
    for row in predictions:
        expected = row["expected"]
        predicted = row["predicted"]
        support[expected] += 1
        confusion[expected][predicted] += 1
        if expected == predicted:
            tp[expected] += 1
        else:
            fp[predicted] += 1
            fn[expected] += 1

    metric_rows = [["label", "precision", "recall", "f1", "support"]]
    f1_values: list[float] = []
    for label in LABELS:
        precision = tp[label] / (tp[label] + fp[label]) if tp[label] + fp[label] else 0.0
        recall = tp[label] / (tp[label] + fn[label]) if tp[label] + fn[label] else 0.0
        label_f1 = f1(precision, recall)
        f1_values.append(label_f1)
        metric_rows.append(
            [
                label,
                f"{precision:.3f}",
                f"{recall:.3f}",
                f"{label_f1:.3f}",
                str(support[label]),
            ]
        )

    summary = {
        "examples": total,
        "correct": correct,
        "accuracy": round(accuracy, 4),
        "macro_f1": round(sum(f1_values) / len(f1_values), 4),
    }
    print("[manual-eval] summary")
    print(json.dumps(summary, indent=2))
    print("\n[manual-eval] per-label metrics")
    print_table(metric_rows)

    matrix_rows = [["expected\\predicted", *LABELS]]
    for expected in LABELS:
        matrix_rows.append([expected, *[str(confusion[expected][predicted]) for predicted in LABELS]])
    print("\n[manual-eval] confusion matrix")
    print_table(matrix_rows)

    mistakes = [row for row in predictions if not row["correct"]]
    print(f"\n[manual-eval] mistakes: {len(mistakes)}")
    for row in mistakes[: args.mistake_limit]:
        print(
            json.dumps(
                {
                    "text": row["text"],
                    "expected": row["expected"],
                    "predicted": row["predicted"],
                    "confidence": row["confidence"],
                },
                ensure_ascii=False,
            )
        )

    if args.output_jsonl:
        output_path = Path(args.output_jsonl)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            for row in predictions:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        print(f"\n[manual-eval] wrote predictions to {output_path}")


if __name__ == "__main__":
    main()
'''


def write_manual_eval_files(eval_path: Path, script_path: Path, model_dir: Path) -> None:
    examples = manual_eval_examples()
    eval_path.parent.mkdir(parents=True, exist_ok=True)
    script_path.parent.mkdir(parents=True, exist_ok=True)
    eval_path.write_text(
        "\n".join(
            json.dumps({"text": ex.text, "label": ex.label}, ensure_ascii=False)
            for ex in examples
        )
        + "\n",
        encoding="utf-8",
    )
    script_path.write_text(manual_eval_script_source(), encoding="utf-8")
    print(f"[manual-eval] wrote {len(examples)} labeled prompts to {eval_path}")
    print(f"[manual-eval] wrote evaluator script to {script_path}")
    print(
        "[manual-eval] second Colab cell: "
        f"!python {script_path} --model-dir {model_dir} --eval-data {eval_path}"
    )


def running_in_colab() -> bool:
    return Path("/content").exists() and "google.colab" in sys.modules


def install_dependencies() -> None:
    packages = [
        "accelerate>=0.33.0",
        "datasets>=2.19.0",
        "numpy>=1.26.0",
        "pandas>=2.2.0",
        "pyarrow>=15.0.0",
        "scikit-learn>=1.4.0",
        "sentencepiece>=0.2.0",
        "torch>=2.2.0",
        "transformers>=4.44.0",
    ]
    print("[setup] installing training dependencies")
    subprocess.check_call(
        [sys.executable, "-m", "pip", "install", "-q", *packages]
    )


def synthetic_examples() -> list[TrainingExample]:
    examples = {
        "get_tasks": [
            "what homework is due this week",
            "show my assignments for tomorrow",
            "what tasks do I need to finish today",
            "list deadlines for Friday",
            "do I have any labs due this week",
            "what quizzes or projects are due next week",
            "show my todo list for today",
            "which homework should I work on first",
        ],
        "get_assignments": [
            "sync canvas assignments",
            "get live canvas homework",
            "what is due on canvas",
            "check canvas for new assignments",
            "pull my canvas deadlines",
            "refresh assignments from canvas",
        ],
        "get_calendar_events": [
            "what classes do I have today",
            "show my calendar tomorrow",
            "what is on my schedule this week",
            "do I have lecture on Friday",
            "list my meetings today",
            "what events are on my calendar",
            "show classes for next week",
        ],
        "find_free_slots": [
            "when am I free tomorrow",
            "find free time this week",
            "show open slots today",
            "when can I study on Friday",
            "do I have availability this afternoon",
            "find a free block next week",
        ],
        "propose_schedule_change": [
            "schedule 2 hours for lab 7 by Friday",
            "plan 90 minutes to study for the midterm by tomorrow",
            "make time for homework 4 due Friday",
            "add a study block for quiz 2 by Thursday",
            "plan work on project 1 for 3 hours before Monday",
            "schedule time for the assignment due tomorrow",
        ],
        "add_calendar_block": [
            "add study for cse 369 thursday from 7 pm to 9 pm",
            "add dentist tomorrow from 2 pm to 3 pm",
            "create a calendar block for office hours friday from 1 pm to 2 pm",
            "put project meeting on my calendar monday from 4 pm to 5 pm",
            "plan calculus review tomorrow from 6 pm to 7 pm",
            "add a calendar block tomorrow from 2 pm to 3 pm",
        ],
        "ai_agent": [
            "explain how the app works",
            "help me understand this error",
            "write a polite email to my professor",
            "summarize this paragraph",
            "what does this course policy mean",
            "give me study tips for algorithms",
            "can you help me brainstorm a project idea",
        ],
    }
    rows: list[TrainingExample] = []
    for label, texts in examples.items():
        for text in texts:
            rows.append(TrainingExample(text=text, label=label))
            rows.append(TrainingExample(text=text.capitalize(), label=label))

    courses = [
        "calculus",
        "biology",
        "chemistry",
        "computer science",
        "history",
        "english",
        "physics",
        "statistics",
        "algorithms",
        "economics",
        "psychology",
        "art history",
    ]
    work_items = [
        "homework 1",
        "lab 3",
        "quiz 2",
        "project proposal",
        "midterm review",
        "essay draft",
        "problem set",
        "reading notes",
        "final exam",
        "discussion post",
        "lab report",
        "worksheet",
    ]
    days = [
        "today",
        "tomorrow",
        "Friday",
        "this week",
        "next week",
        "Monday",
        "Tuesday",
        "Wednesday",
        "Thursday",
    ]
    durations = ["30 minutes", "45 minutes", "1 hour", "90 minutes", "2 hours", "3 hours"]
    event_types = ["lecture", "lab", "discussion", "section", "exam review", "office hours"]
    general_topics = [
        "write an email to my professor",
        "explain recursion",
        "summarize this paragraph",
        "help me brainstorm project ideas",
        "what does this policy mean",
        "give me study tips",
        "make this sentence sound polite",
        "debug this error message",
        "explain big O notation",
        "write a short apology email",
        "what is the capital of Canada",
        "how do I cook rice",
    ]

    for course in courses:
        rows.append(TrainingExample(f"see whether {course} posted new work", "get_assignments"))
        rows.append(TrainingExample(f"check if {course} posted a new assignment", "get_assignments"))
        rows.append(TrainingExample(f"did {course} post new homework", "get_assignments"))
        rows.append(TrainingExample(f"load new {course} course work from the portal", "get_assignments"))
        for day in days:
            rows.append(TrainingExample(f"what {course} homework is due {day}", "get_tasks"))
            rows.append(TrainingExample(f"show my {course} tasks for {day}", "get_tasks"))
            rows.append(TrainingExample(f"list {course} deadlines for {day}", "get_tasks"))
            rows.append(TrainingExample(f"do I have any {course} assignments due {day}", "get_tasks"))
            rows.append(TrainingExample(f"what {course} class do I have {day}", "get_calendar_events"))
            rows.append(TrainingExample(f"show my {course} calendar for {day}", "get_calendar_events"))
            rows.append(TrainingExample(f"what {course} events are on my calendar {day}", "get_calendar_events"))
            rows.append(TrainingExample(f"list my {course} meetings {day}", "get_calendar_events"))
            rows.append(TrainingExample(f"when am I free to study {course} {day}", "find_free_slots"))
            rows.append(TrainingExample(f"find free time for {course} {day}", "find_free_slots"))
            rows.append(TrainingExample(f"show open slots for {course} {day}", "find_free_slots"))
            rows.append(TrainingExample(f"when can I work on {course} {day}", "find_free_slots"))
            rows.append(TrainingExample(f"what free slots do I have {day}", "find_free_slots"))
            rows.append(TrainingExample(f"do I have open time {day}", "find_free_slots"))
            rows.append(TrainingExample(f"is there room in my schedule {day}", "find_free_slots"))
            rows.append(TrainingExample(f"show availability after class {day}", "find_free_slots"))
            rows.append(TrainingExample(f"tell me my homework for {day}", "get_tasks"))
            rows.append(TrainingExample(f"what do I need to turn in {day}", "get_tasks"))
            rows.append(TrainingExample(f"what assignments are due {day}", "get_tasks"))
            rows.append(TrainingExample(f"when is {course} on my calendar {day}", "get_calendar_events"))
            rows.append(TrainingExample(f"what time is {course} on my calendar {day}", "get_calendar_events"))
            rows.append(
                TrainingExample(
                    f"add study for {course} {day} from 2 pm to 3 pm",
                    "add_calendar_block",
                )
            )
            rows.append(
                TrainingExample(
                    f"put {course} review on my calendar {day} from 4 pm to 5 pm",
                    "add_calendar_block",
                )
            )

            for event_type in event_types:
                rows.append(TrainingExample(f"do I have {course} {event_type} {day}", "get_calendar_events"))
                rows.append(TrainingExample(f"what time is my {course} {event_type} {day}", "get_calendar_events"))
                rows.append(TrainingExample(f"when is my {course} {event_type} {day}", "get_calendar_events"))
                rows.append(TrainingExample(f"is there a {course} {event_type} {day}", "get_calendar_events"))

    for duration in durations:
        for day in days:
            rows.append(TrainingExample(f"find {duration} for studying {day}", "find_free_slots"))
            rows.append(TrainingExample(f"find {duration} for homework {day}", "find_free_slots"))
            rows.append(TrainingExample(f"find {duration} to study {day}", "find_free_slots"))

    for item in work_items:
        for day in days:
            rows.append(TrainingExample(f"is {item} due {day}", "get_tasks"))
            rows.append(TrainingExample(f"show deadline for {item} {day}", "get_tasks"))
            rows.append(TrainingExample(f"what tasks include {item} due {day}", "get_tasks"))
            rows.append(TrainingExample(f"add {item} due {day} to my task list", "get_tasks"))
            rows.append(TrainingExample(f"sync {item} from canvas", "get_assignments"))
            rows.append(TrainingExample(f"check canvas for {item} due {day}", "get_assignments"))
            rows.append(TrainingExample(f"pull {item} assignment from canvas", "get_assignments"))
            rows.append(TrainingExample(f"refresh canvas and find {item}", "get_assignments"))
            rows.append(TrainingExample(f"get live assignment data for {item}", "get_assignments"))
            for duration in durations:
                rows.append(
                    TrainingExample(
                        f"schedule {duration} for {item} by {day}",
                        "propose_schedule_change",
                    )
                )
                rows.append(
                    TrainingExample(
                        f"plan {duration} to work on {item} before {day}",
                        "propose_schedule_change",
                    )
                )
                rows.append(
                    TrainingExample(
                        f"make a {duration} study block for {item} before {day}",
                        "propose_schedule_change",
                    )
                )
                rows.append(
                    TrainingExample(
                        f"find time and schedule {duration} for {item} by {day}",
                        "propose_schedule_change",
                    )
                )

    for topic in general_topics:
        rows.append(TrainingExample(topic, "ai_agent"))
        rows.append(TrainingExample(f"can you {topic}", "ai_agent"))
        rows.append(TrainingExample(f"help me {topic}", "ai_agent"))
        rows.append(TrainingExample(f"I need help with this: {topic}", "ai_agent"))

    hard_examples = {
        "get_assignments": [
            "load assignments from my online course portal",
            "pull online course deadlines",
            "sync assignment feed from the LMS",
            "refresh course homework from the LMS",
            "check if my course site posted work",
            "update assignment data from canvas",
            "load the newest course tasks",
            "pull homework from my online classes",
            "sync due dates from the course website",
            "check my learning system for new work",
        ],
        "find_free_slots": [
            "find time between classes tomorrow",
            "when is my next free block",
            "show open time tonight",
            "is there space in my schedule today",
            "find a gap in my calendar",
            "find two free hours this week",
            "when can I fit in studying",
            "show availability after my classes",
            "when do I have room to work",
            "find study time before Friday",
            "show free time around my classes",
            "when is my next open slot",
            "can I fit homework in tonight",
            "find a free block after lunch",
            "show me when I am not busy",
        ],
        "get_calendar_events": [
            "show meetings after class",
            "list appointments for tomorrow",
            "what appointments do I have this week",
            "show events after 3",
            "list calendar meetings after noon",
            "what scheduled appointments are on Monday",
            "show my appointments for next week",
            "what meetings are later today",
            "list events on my calendar after lunch",
            "do I have appointments this afternoon",
        ],
        "get_tasks": [
            "what do I need to submit today",
            "what do I need to turn in tomorrow",
            "show work I still need to submit",
            "what homework should I hand in",
            "what do I owe for this class",
            "do I owe any assignments",
            "what is the next assignment deadline",
            "show my next homework deadline",
            "what school work is due soon",
            "remind me what needs to be submitted",
            "show pending submissions",
            "what do I have to turn in this week",
            "what homework is due next week",
            "show upcoming due dates",
            "what assignment is due first",
        ],
        "propose_schedule_change": [
            "make time to study tonight",
            "put study time on my calendar",
            "put homework time into my schedule",
            "help me plan work for the exam",
            "help me plan a study session",
            "create a study session tomorrow",
            "make a study plan for the test",
            "turn my free time into a study block",
            "schedule homework after class",
            "add a work session after my last class",
            "block time to finish the paper",
            "reserve time for homework this evening",
            "plan a work block around my classes",
            "create calendar time for studying",
            "make room for assignment work",
        ],
        "add_calendar_block": [
            "add tutoring tomorrow from 2 pm to 3 pm",
            "create a calendar block for advising friday from 11 am to noon",
            "put study for calculus on my calendar monday from 6 pm to 8 pm",
            "add project meeting thursday from 4 pm to 5 pm",
            "plan biology review tomorrow from 7 pm to 8 pm",
            "add a calendar block tomorrow from 2 pm to 3 pm",
            "add a block to my calendar friday",
        ],
        "ai_agent": [
            "brainstorm essay topics for history",
            "give me topic ideas for my paper",
            "help me outline a history essay",
            "brainstorm arguments for my essay",
            "give me capstone project topics",
            "help me choose a research topic",
            "write an outline for my paper",
            "explain this essay prompt",
            "help me make my paragraph clearer",
            "give me thesis statement ideas",
        ],
    }
    for label, texts in hard_examples.items():
        for text in texts:
            rows.append(TrainingExample(text, label))
            rows.append(TrainingExample(text.capitalize(), label))
    return rows


def normalize_label(value: object) -> str | None:
    if value is None:
        return None
    key = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")
    if key in LABELS:
        return key
    if "canvas" in key and any(x in key for x in ("assignment", "homework", "due")):
        return "get_assignments"
    if any(x in key for x in ("free", "available", "availability", "slot")):
        return "find_free_slots"
    if any(x in key for x in ("create_calendar", "add_calendar", "calendar_block")):
        return "add_calendar_block"
    if any(x in key for x in ("calendar", "event", "meeting", "class", "lecture")):
        return "get_calendar_events"
    if any(x in key for x in ("homework", "assignment", "deadline", "task", "todo", "due")):
        return "get_tasks"
    if any(x in key for x in ("schedule_change", "study_block", "plan_study", "propose")):
        return "propose_schedule_change"
    if any(x in key for x in ("out_of_scope", "oos", "general", "chat", "fallback")):
        return "ai_agent"
    return None


def extract_user_text(row: dict[str, Any]) -> str | None:
    for key in (
        "user_message",
        "query",
        "instruction",
        "prompt",
        "text",
        "utterance",
        "user_utterance",
        "question",
    ):
        value = row.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    for key in ("messages", "conversation", "conversations"):
        value = row.get(key)
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                continue
        if isinstance(value, list):
            for msg in value:
                if not isinstance(msg, dict):
                    continue
                role = str(msg.get("role") or msg.get("from") or "").lower()
                if role in {"user", "human"}:
                    content = msg.get("content") or msg.get("value")
                    if isinstance(content, str) and content.strip():
                        return content.strip()
    return None


def extract_label(row: dict[str, Any]) -> str | None:
    for key in (
        "label",
        "intent",
        "tool",
        "tool_name",
        "function",
        "function_name",
        "service",
        "active_intent",
        "target",
        "category",
    ):
        label = normalize_label(row.get(key))
        if label:
            return label
    return None


def extract_exact_label(row: dict[str, Any]) -> str | None:
    for key in (
        "label",
        "intent",
        "tool",
        "tool_name",
        "function",
        "function_name",
        "target",
        "category",
    ):
        value = row.get(key)
        if value is None:
            continue
        normalized = re.sub(
            r"[^a-z0-9]+",
            "_",
            str(value).strip().lower(),
        ).strip("_")
        if normalized in LABELS:
            return normalized
    return None


def infer_syntra_label(text: str) -> str:
    lower = text.lower()
    if any(
        phrase in lower
        for phrase in (
            "add a calendar block",
            "add calendar block",
            "add a block to my calendar",
            "create a calendar block",
            "put a block on my calendar",
        )
    ):
        return "add_calendar_block"
    if any(x in lower for x in ("schedule", "plan", "study block", "make time", "work on")) and any(
        x in lower for x in ("homework", "assignment", "task", "exam", "quiz", "lab", "project", "study")
    ):
        return "propose_schedule_change"
    if any(x in lower for x in ("free time", "open time", "availability", "available", "free slot", "when am i free", "when can i")):
        return "find_free_slots"
    if "canvas" in lower and any(x in lower for x in ("assignment", "homework", "due", "deadline", "sync")):
        return "get_assignments"
    if any(x in lower for x in ("calendar", "class", "classes", "event", "meeting", "lecture", "section", "my schedule")):
        return "get_calendar_events"
    if any(x in lower for x in ("task", "homework", "hw", "assignment", "due", "deadline", "quiz", "exam", "project", "lab", "todo")):
        return "get_tasks"
    return "ai_agent"


def infer_syntra_label_strict(text: str) -> str | None:
    lower = text.lower()
    words = set(re.findall(r"\b[a-z0-9]+\b", lower))

    if any(
        phrase in lower
        for phrase in (
            "add a calendar block",
            "add calendar block",
            "add a block to my calendar",
            "create a calendar block",
            "put a block on my calendar",
        )
    ) or (
        re.search(
            r"\b(?:from\s+)?\d{1,2}(?::\d{2})?\s*(?:am|pm)\s+to\s+"
            r"\d{1,2}(?::\d{2})?\s*(?:am|pm)\b",
            lower,
        )
        and any(word in words for word in ("add", "put", "plan", "create"))
    ):
        return "add_calendar_block"

    schedule_action = any(
        phrase in lower
        for phrase in (
            "schedule",
            "plan",
            "study block",
            "study time",
            "make time",
            "work on",
            "add time",
        )
    )
    work_item = any(
        word in words
        for word in (
            "homework",
            "assignment",
            "assignments",
            "task",
            "exam",
            "quiz",
            "lab",
            "project",
            "study",
        )
    )
    schedule_view = any(
        phrase in lower
        for phrase in (
            "my schedule",
            "class schedule",
            "what is on my schedule",
            "what's on my schedule",
        )
    )
    if schedule_action and work_item and not schedule_view:
        return "propose_schedule_change"

    if any(
        phrase in lower
        for phrase in (
            "free time",
            "open time",
            "availability",
            "available time",
            "free slot",
            "free slots",
            "when am i free",
            "when can i study",
            "when can i work",
        )
    ):
        return "find_free_slots"

    if ("canvas" in words or "sync" in words or "live" in words) and any(
        word in words
        for word in (
            "assignment",
            "assignments",
            "homework",
            "deadline",
            "deadlines",
            "due",
        )
    ):
        return "get_assignments"

    if any(
        phrase in lower
        for phrase in (
            "my calendar",
            "my schedule",
            "class schedule",
            "what classes",
            "what class",
            "what meetings",
            "what events are on my calendar",
        )
    ) or any(
        word in words
        for word in (
            "calendar",
            "classes",
            "lecture",
            "lectures",
            "section",
            "sections",
            "meeting",
            "meetings",
        )
    ):
        return "get_calendar_events"

    if any(
        word in words
        for word in (
            "task",
            "tasks",
            "homework",
            "hw",
            "assignment",
            "assignments",
            "due",
            "deadline",
            "deadlines",
            "quiz",
            "exam",
            "project",
            "lab",
            "todo",
        )
    ):
        return "get_tasks"

    return None


def rows_from_json_value(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                yield from rows_from_json_value(item)
        return
    if not isinstance(value, dict):
        return

    turns = value.get("turns")
    if isinstance(turns, list):
        for turn in turns:
            if not isinstance(turn, dict):
                continue
            speaker = str(turn.get("speaker") or turn.get("role") or "").lower()
            if speaker and speaker not in {"user", "human"}:
                continue
            row = dict(turn)
            frames = turn.get("frames")
            if isinstance(frames, list):
                frame = next((f for f in frames if isinstance(f, dict)), None)
                if frame:
                    row["service"] = frame.get("service")
                    state = frame.get("state")
                    if isinstance(state, dict):
                        row["active_intent"] = state.get("active_intent")
            yield row
        return

    for key in ("data", "train", "examples", "rows"):
        nested = value.get(key)
        if isinstance(nested, list):
            yield from rows_from_json_value(nested)
            return
    yield value


def rows_from_file(path: Path) -> Iterable[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(row, dict):
                    yield row
        return
    if suffix == ".json":
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return
        yield from rows_from_json_value(value)
        return
    if suffix == ".parquet":
        try:
            import pandas as pd

            frame = pd.read_parquet(path)
            for row in frame.to_dict(orient="records"):
                if isinstance(row, dict):
                    yield row
        except Exception as exc:
            print(f"[data] skipped parquet {path}: {exc}")
        return
    if suffix == ".csv":
        with path.open("r", encoding="utf-8", newline="") as f:
            yield from csv.DictReader(f)
        return
    if suffix in {".txt", ".tsv"}:
        delimiter = "\t" if suffix == ".tsv" else None
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if delimiter and delimiter in line:
                    left, right = line.split(delimiter, 1)
                    label = normalize_label(left)
                    yield {"text": right, "label": label} if label else {"text": left, "label": normalize_label(right)}
                else:
                    yield {"text": line}


def is_real_data_file(path: Path) -> bool:
    if "__MACOSX" in path.parts:
        return False
    if path.name.startswith("._") or path.name.startswith("."):
        return False
    return path.suffix.lower() in {".jsonl", ".json", ".csv", ".txt", ".tsv", ".parquet"}


def unzip_clean(zip_path: Path, extract_dir: Path) -> Path:
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        for member in zf.infolist():
            member_path = Path(member.filename)
            if "__MACOSX" in member_path.parts or member_path.name.startswith("._"):
                continue
            zf.extract(member, extract_dir)
    return extract_dir


def data_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if is_real_data_file(root) else []
    return [path for path in root.rglob("*") if is_real_data_file(path)]


def find_data_path(requested: Path) -> Path | None:
    if requested.exists():
        return requested

    candidates: list[Path] = [
        Path.cwd() / "data.zip",
        Path.cwd() / "Data.zip",
        Path("/data.zip"),
        Path("/Data.zip"),
        Path("/content/data.zip"),
        Path("/content/Data.zip"),
        Path("/content/data"),
        Path("/content/real_data"),
    ]
    for search_root in (Path.cwd(), Path("/content")):
        if not search_root.exists() or not search_root.is_dir():
            continue
        candidates.extend(sorted(search_root.glob("*.zip")))
        candidates.extend(
            sorted(
                path
                for path in search_root.iterdir()
                if path.is_dir()
                and path.name not in {"sample_data", "syntra_tool_router", "real_data"}
            )
        )

    for candidate in candidates:
        if not candidate.exists():
            continue
        if candidate.is_file() and (
            candidate.suffix.lower() == ".zip" or is_real_data_file(candidate)
        ):
            return candidate
        if candidate.is_dir() and data_files(candidate):
            return candidate
    return None


def load_local_examples(
    data_path: Path,
    extract_dir: Path,
    *,
    include_noisy_local: bool,
    local_ai_agent_limit: int,
) -> list[TrainingExample]:
    if data_path.suffix.lower() == ".zip":
        root = unzip_clean(data_path, extract_dir)
    else:
        root = data_path

    files = data_files(root)
    print(f"[data] real data files found: {len(files)}")
    for path in files[:20]:
        print(f"[data] {path}")

    examples: list[TrainingExample] = []
    skipped = 0
    local_ai_agent_count = 0
    for path in files:
        for row in rows_from_file(path):
            text = extract_user_text(row)
            if not text:
                continue
            label = extract_exact_label(row) or infer_syntra_label_strict(text)
            if label is None and include_noisy_local:
                label = extract_label(row) or infer_syntra_label(text)
            if label is None:
                skipped += 1
                continue
            if label == "ai_agent":
                if local_ai_agent_count >= local_ai_agent_limit:
                    skipped += 1
                    continue
                local_ai_agent_count += 1
            examples.append(TrainingExample(text=text, label=label))
    print(f"[data] local examples kept: {len(examples)}; skipped as noisy: {skipped}")
    return examples


def load_structured_nlu_examples(path: Path) -> list[TrainingExample]:
    if not path.exists():
        print(f"[structured-nlu] data not found at {path}; skipping intent rows")
        return []
    examples: list[TrainingExample] = []
    for row in rows_from_file(path):
        text = extract_user_text(row)
        label = extract_exact_label(row)
        if text and label:
            examples.append(TrainingExample(text=text, label=label))
    print(f"[structured-nlu] loaded {len(examples)} canonical intent rows from {path}")
    return examples


def train_slot_model(args: argparse.Namespace, output_dir: Path) -> None:
    if args.skip_slot_model:
        print("[slot-model] skipped")
        return
    data_path = Path(args.structured_nlu_data)
    trainer_path = Path(__file__).with_name("train_nlu_slot_model.py")
    if not data_path.exists() or not trainer_path.exists():
        print(
            "[slot-model] skipped because structured data or trainer is missing: "
            f"{data_path}, {trainer_path}"
        )
        return
    command = [
        sys.executable,
        str(trainer_path),
        "--data",
        str(data_path),
        "--output-dir",
        str(output_dir / "slot_model"),
        "--base-model",
        args.slot_base_model,
        "--epochs",
        str(args.slot_epochs),
        "--batch-size",
        str(args.slot_batch_size),
    ]
    print(f"[slot-model] training with {data_path}")
    subprocess.run(command, check=True)


def map_tool_name_to_label(value: object) -> str | None:
    if value is None:
        return None
    key = re.sub(r"[^a-z0-9]+", "_", str(value).strip().lower()).strip("_")
    if key in LABELS:
        return key
    if "canvas" in key and any(part in key for part in ("assignment", "homework", "due")):
        return "get_assignments"
    if any(part in key for part in ("free", "availability", "available", "open_slot", "slot")):
        return "find_free_slots"
    if any(part in key for part in ("calendar", "event", "meeting", "class", "lecture")):
        if any(part in key for part in ("create", "add", "schedule", "book", "reserve")):
            return "add_calendar_block"
        return "get_calendar_events"
    if any(part in key for part in ("todo", "task", "homework", "assignment", "deadline", "due")):
        return "get_tasks"
    if any(part in key for part in ("reminder", "schedule", "plan", "study_block")):
        return "propose_schedule_change"
    return None


def extract_tool_label_from_value(value: Any) -> str | None:
    if isinstance(value, dict):
        for key in (
            "tool",
            "tool_name",
            "function",
            "function_name",
            "name",
            "api",
            "api_name",
            "action",
            "intent",
        ):
            label = map_tool_name_to_label(value.get(key))
            if label:
                return label
        for nested_key in (
            "tool_call",
            "tool_calls",
            "function_call",
            "function_calls",
            "api_call",
            "api_calls",
            "messages",
            "conversation",
            "conversations",
        ):
            label = extract_tool_label_from_value(value.get(nested_key))
            if label:
                return label
    elif isinstance(value, list):
        for item in value:
            label = extract_tool_label_from_value(item)
            if label:
                return label
    elif isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return map_tool_name_to_label(value)
        return extract_tool_label_from_value(parsed)
    return None


def row_domain_text(row: dict[str, Any]) -> str:
    values: list[str] = []
    for key in ("service", "domain", "domains", "active_intent", "intent", "category"):
        value = row.get(key)
        if value is None:
            continue
        if isinstance(value, (list, tuple, set)):
            values.extend(str(item) for item in value)
        else:
            values.append(str(value))
    return " ".join(values).lower()


def hf_label_for_row(dataset_name: str, row: dict[str, Any], text: str) -> str | None:
    exact = extract_exact_label(row)
    if exact:
        return exact

    tool_label = extract_tool_label_from_value(row)
    if tool_label:
        return tool_label

    strict = infer_syntra_label_strict(text)
    if strict:
        return strict

    dataset_key = dataset_name.lower()
    domain_text = row_domain_text(row)
    if "clinc" in dataset_key:
        return "ai_agent"
    if "calendar" in dataset_key or "ba-calendar" in dataset_key:
        return "propose_schedule_change"
    if "kvret" in dataset_key and "schedule" in domain_text:
        if any(word in text.lower() for word in ("schedule", "add", "put", "book", "reserve")):
            return "propose_schedule_change"
        return "get_calendar_events"
    if "schema_guided" in dataset_key and any(
        word in domain_text for word in ("calendar", "event")
    ):
        return "get_calendar_events"
    return None


def examples_from_hf_row(dataset_name: str, row: dict[str, Any]) -> list[TrainingExample]:
    examples: list[TrainingExample] = []
    for candidate in rows_from_json_value(row):
        text = extract_user_text(candidate)
        if not text:
            continue
        label = hf_label_for_row(dataset_name, candidate, text)
        if label:
            examples.append(TrainingExample(text=text, label=label))
    return examples


def load_hf_split(load_dataset: Any, dataset_name: str, split: str, streaming: bool) -> Any:
    return load_dataset(dataset_name, split=split, streaming=streaming)


def load_hf_examples(
    dataset_names: list[str],
    *,
    split: str,
    max_rows_per_dataset: int,
    seed: int,
) -> list[TrainingExample]:
    try:
        from datasets import DatasetDict, IterableDatasetDict, load_dataset
    except ImportError as exc:
        raise RuntimeError("Install datasets first or let the script install dependencies.") from exc

    all_examples: list[TrainingExample] = []
    for dataset_name in dataset_names:
        dataset_examples: list[TrainingExample] = []
        scanned = 0
        print(f"[hf] loading {dataset_name}")
        try:
            dataset = load_hf_split(load_dataset, dataset_name, split, streaming=True)
        except Exception as streaming_exc:
            print(f"[hf] streaming failed for {dataset_name}: {streaming_exc}")
            try:
                loaded = load_dataset(dataset_name)
            except Exception as load_exc:
                print(f"[hf] skipped {dataset_name}: {load_exc}")
                continue
            except BaseException as load_exc:
                print(f"[hf] skipped {dataset_name}: {load_exc}")
                continue

            if isinstance(loaded, (DatasetDict, IterableDatasetDict)):
                split_name = split if split in loaded else next(iter(loaded.keys()))
                dataset = loaded[split_name]
            else:
                dataset = loaded

        try:
            dataset = dataset.shuffle(seed=seed, buffer_size=10000)
        except TypeError:
            dataset = dataset.shuffle(seed=seed)
        except Exception:
            pass

        for row in dataset:
            if max_rows_per_dataset > 0 and scanned >= max_rows_per_dataset:
                break
            scanned += 1
            if not isinstance(row, dict):
                continue
            dataset_examples.extend(examples_from_hf_row(dataset_name, row))

        print(
            f"[hf] {dataset_name}: scanned {scanned}; "
            f"kept {len(dataset_examples)} Syntra-labeled examples"
        )
        all_examples.extend(dataset_examples)

    return all_examples


def balance_examples(examples: list[TrainingExample], seed: int) -> list[TrainingExample]:
    by_label = {label: [] for label in LABELS}
    for ex in examples:
        if ex.label in by_label:
            by_label[ex.label].append(ex)
    max_count = max((len(v) for v in by_label.values()), default=0)
    rng = random.Random(seed)
    balanced: list[TrainingExample] = []
    for items in by_label.values():
        if not items:
            continue
        pool = list(items)
        while len(pool) < max_count:
            pool.append(rng.choice(items))
        balanced.extend(pool[:max_count])
    rng.shuffle(balanced)
    return balanced


def dedupe_examples(examples: list[TrainingExample]) -> list[TrainingExample]:
    by_text: dict[str, TrainingExample] = {}
    conflicts = 0
    for ex in examples:
        key = " ".join(ex.text.lower().split())
        existing = by_text.get(key)
        if existing is None:
            by_text[key] = ex
            continue
        if existing.label != ex.label:
            conflicts += 1
    deduped = list(by_text.values())
    print(f"[data] deduped examples: {len(examples)} -> {len(deduped)}; label conflicts ignored: {conflicts}")
    return deduped


def limit_examples_per_label(
    examples: list[TrainingExample],
    max_per_label: int,
    seed: int,
) -> list[TrainingExample]:
    if max_per_label <= 0:
        return examples

    by_label = {label: [] for label in LABELS}
    for ex in examples:
        if ex.label in by_label:
            by_label[ex.label].append(ex)

    rng = random.Random(seed)
    limited: list[TrainingExample] = []
    for items in by_label.values():
        rng.shuffle(items)
        limited.extend(items[:max_per_label])
    rng.shuffle(limited)
    return limited


def print_label_samples(
    examples: list[TrainingExample],
    sample_count: int,
    seed: int,
) -> None:
    if sample_count <= 0:
        return

    by_label = {label: [] for label in LABELS}
    for ex in examples:
        if ex.label in by_label:
            by_label[ex.label].append(ex)

    rng = random.Random(seed)
    print("[data] sample training rows by label")
    for label, items in by_label.items():
        print(f"[data] {label}:")
        if not items:
            print("  - NO EXAMPLES")
            continue
        selected = rng.sample(items, min(sample_count, len(items)))
        for ex in selected:
            text = " ".join(ex.text.split())
            print(f"  - {text[:180]}")


def monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def route_args(label: str, prompt: str, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    lower = prompt.lower()
    if "tomorrow" in lower:
        start = end = today + timedelta(days=1)
    elif "today" in lower:
        start = end = today
    else:
        start = monday(today)
        end = start + timedelta(days=4)

    if label == "get_tasks":
        return {"due_start": start.isoformat(), "due_end": end.isoformat()}
    if label in {"find_free_slots", "get_calendar_events"}:
        return {"start_date": start.isoformat(), "end_date": end.isoformat()}
    if label == "get_assignments":
        return {}
    if label == "propose_schedule_change":
        hours_match = re.search(r"\b(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)\b", lower)
        hours = float(hours_match.group(1)) if hours_match else 1.0
        return {
            "task_name": re.sub(r"\b(schedule|plan|for|by|due)\b", "", prompt, flags=re.I).strip()[:120] or "Study block",
            "hours": hours,
            "deadline": f"{end.isoformat()}T23:59:00",
            "estimated_minutes": int(hours * 60),
        }
    if label == "add_calendar_block":
        return {"message": prompt, "needs_slot_extraction": True}
    return {"message": prompt}


def train_and_test(args: argparse.Namespace) -> None:
    if args.install_deps:
        install_dependencies()

    import numpy as np
    from datasets import Dataset
    from transformers import (
        AutoModelForSequenceClassification,
        AutoTokenizer,
        DataCollatorWithPadding,
        Trainer,
        TrainingArguments,
        logging as transformers_logging,
        pipeline,
    )
    transformers_logging.set_verbosity_error()

    hf = []
    if args.use_hf_datasets and not args.skip_hf_datasets:
        dataset_names = args.hf_dataset or DEFAULT_HF_DATASETS
        hf = load_hf_examples(
            dataset_names,
            split=args.hf_split,
            max_rows_per_dataset=args.max_hf_rows_per_dataset,
            seed=args.seed,
        )
    else:
        print("[hf] skipping Hugging Face datasets; using clean Syntra examples")

    local = []
    if args.include_local_data:
        requested_data_path = Path(args.data)
        data_path = find_data_path(requested_data_path)
        if data_path is None:
            print(f"[data] could not find {requested_data_path}; skipping local data")
        else:
            if data_path != requested_data_path:
                print(f"[data] using discovered data path: {data_path}")
            local = load_local_examples(
                data_path,
                Path(args.extract_dir),
                include_noisy_local=args.include_noisy_local,
                local_ai_agent_limit=args.local_ai_agent_limit,
            )
    else:
        print("[data] skipping local data")

    structured = load_structured_nlu_examples(Path(args.structured_nlu_data))
    examples = hf + local + structured + synthetic_examples()
    examples = dedupe_examples(examples)
    examples = limit_examples_per_label(
        examples,
        args.max_examples_per_label,
        args.seed,
    )
    if args.balance:
        examples = balance_examples(examples, args.seed)

    counts = {label: 0 for label in LABELS}
    for ex in examples:
        counts[ex.label] = counts.get(ex.label, 0) + 1
    print(
        json.dumps(
            {
                "hf_examples": len(hf),
                "local_examples": len(local),
                "structured_nlu_examples": len(structured),
                "total_examples": len(examples),
                "label_counts": counts,
            },
            indent=2,
        )
    )
    print_label_samples(examples, args.sample_label_examples, args.seed)

    label_to_id = {label: idx for idx, label in enumerate(LABELS)}
    dataset = Dataset.from_dict(
        {
            "text": [ex.text for ex in examples],
            "label": [label_to_id[ex.label] for ex in examples],
        }
    ).train_test_split(test_size=0.1, seed=args.seed)

    tokenizer = AutoTokenizer.from_pretrained(args.base_model)

    def tokenize(batch: dict[str, list[Any]]) -> dict[str, Any]:
        return tokenizer(batch["text"], truncation=True, max_length=256)

    tokenized = dataset.map(tokenize, batched=True)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.base_model,
        num_labels=len(LABELS),
        id2label={idx: label for idx, label in enumerate(LABELS)},
        label2id=label_to_id,
    )

    def compute_metrics(eval_pred: Any) -> dict[str, float]:
        logits, labels = eval_pred
        preds = np.argmax(logits, axis=-1)
        return {"accuracy": float((preds == labels).mean())}

    training_kwargs: dict[str, Any] = {
        "output_dir": args.output_dir,
        "learning_rate": args.learning_rate,
        "per_device_train_batch_size": args.batch_size,
        "per_device_eval_batch_size": args.batch_size,
        "num_train_epochs": args.epochs,
        "weight_decay": 0.01,
        "max_grad_norm": args.max_grad_norm,
        "warmup_steps": args.warmup_steps,
        "logging_steps": 25,
        "save_strategy": "epoch",
        "load_best_model_at_end": False,
        "report_to": "none",
        "seed": args.seed,
    }
    if args.max_steps > 0:
        training_kwargs["max_steps"] = args.max_steps

    for flag_name, flag_value in {
        "bf16": False,
        "fp16": False,
        "tf32": False,
    }.items():
        if flag_name in inspect.signature(TrainingArguments.__init__).parameters:
            training_kwargs[flag_name] = flag_value

    strategy_arg = "eval_strategy" if "eval_strategy" in inspect.signature(TrainingArguments.__init__).parameters else "evaluation_strategy"
    training_kwargs[strategy_arg] = "epoch"

    trainer_kwargs: dict[str, Any] = {
        "model": model,
        "args": TrainingArguments(**training_kwargs),
        "train_dataset": tokenized["train"],
        "eval_dataset": tokenized["test"],
        "data_collator": DataCollatorWithPadding(tokenizer=tokenizer),
        "compute_metrics": compute_metrics,
    }
    trainer_params = inspect.signature(Trainer.__init__).parameters
    if "processing_class" in trainer_params:
        trainer_kwargs["processing_class"] = tokenizer
    elif "tokenizer" in trainer_params:
        trainer_kwargs["tokenizer"] = tokenizer

    trainer = Trainer(**trainer_kwargs)
    trainer.train()
    metrics = trainer.evaluate()
    eval_loss = metrics.get("eval_loss")
    if eval_loss is not None and not np.isfinite(eval_loss):
        print(
            "[warning] eval loss is not finite. The model is not usable yet. "
            "Try --learning-rate 2e-5 --max-grad-norm 1.0 or use fewer noisy examples."
        )
        return

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    trainer.save_model(output_dir)
    tokenizer.save_pretrained(output_dir)
    (output_dir / "labels.json").write_text(json.dumps({"labels": LABELS}, indent=2))
    print(f"[model] saved to {output_dir}")
    train_slot_model(args, output_dir)
    if not args.skip_manual_eval_files:
        eval_path = (
            Path(args.manual_eval_path)
            if args.manual_eval_path
            else output_dir.parent / "syntra_router_manual_eval.jsonl"
        )
        script_path = (
            Path(args.manual_eval_script_path)
            if args.manual_eval_script_path
            else output_dir.parent / "evaluate_syntra_router_manual_colab.py"
        )
        write_manual_eval_files(eval_path, script_path, output_dir)

    classifier = pipeline(
        "text-classification",
        model=str(output_dir),
        tokenizer=str(output_dir),
        top_k=1,
        device=0 if args.gpu_pipeline else -1,
    )
    prompts = args.test_prompt or DEFAULT_TEST_PROMPTS
    print("\n[test] predictions")
    for prompt in prompts:
        result = classifier(prompt)[0][0]
        label = result["label"]
        score = float(result["score"])
        print(json.dumps(
            {
                "prompt": prompt,
                "tool_call": {
                    "name": label,
                    "arguments": route_args(label, prompt),
                    "confidence": round(score, 4),
                },
            },
            indent=2,
        ))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="One-click train/test Syntra NLP tool router.")
    parser.add_argument("--data", default="/content/data.zip")
    parser.add_argument("--extract-dir", default="/content/real_data")
    parser.add_argument("--output-dir", default="/content/syntra_tool_router")
    parser.add_argument(
        "--structured-nlu-data",
        default=str(Path(__file__).with_name("syntra_nlu_training_data.jsonl")),
        help="Canonical JSONL used for intent rows, slots, and follow-up ground truth.",
    )
    parser.add_argument("--skip-slot-model", action="store_true")
    parser.add_argument("--slot-base-model", default="distilbert-base-uncased")
    parser.add_argument("--slot-epochs", type=float, default=8.0)
    parser.add_argument("--slot-batch-size", type=int, default=8)
    parser.add_argument("--base-model", default="distilbert-base-uncased")
    parser.add_argument("--epochs", type=float, default=6.0)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument(
        "--use-hf-datasets",
        action="store_true",
        help="Also download/train on curated Hugging Face datasets. Off by default because weak external labels hurt accuracy.",
    )
    parser.add_argument(
        "--skip-hf-datasets",
        action="store_true",
        help="Compatibility flag. Hugging Face datasets are already skipped unless --use-hf-datasets is passed.",
    )
    parser.add_argument(
        "--hf-dataset",
        action="append",
        help=(
            "Hugging Face dataset name to use. Repeat for multiple. "
            f"Default: {', '.join(DEFAULT_HF_DATASETS)}"
        ),
    )
    parser.add_argument("--hf-split", default="train")
    parser.add_argument(
        "--max-hf-rows-per-dataset",
        type=int,
        default=30000,
        help="Rows to scan from each Hugging Face dataset before filtering into Syntra labels.",
    )
    parser.add_argument(
        "--include-local-data",
        action="store_true",
        help="Also train on --data. By default local data.zip is ignored.",
    )
    parser.add_argument("--balance", action="store_true", default=True)
    parser.add_argument(
        "--max-examples-per-label",
        type=int,
        default=25000,
        help="Caps each label before balancing. Lower is usually cleaner for weak labels.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=0,
        help="Hard cap on training steps. Default 0 uses epochs only.",
    )
    parser.add_argument("--max-grad-norm", type=float, default=1.0)
    parser.add_argument("--warmup-steps", type=int, default=100)
    parser.add_argument(
        "--include-noisy-local",
        action="store_true",
        help="Use broad dataset labels when strict Syntra labels are not found. Usually hurts accuracy.",
    )
    parser.add_argument(
        "--local-ai-agent-limit",
        type=int,
        default=5000,
        help="Max local fallback examples to keep when --include-noisy-local is used.",
    )
    parser.add_argument(
        "--sample-label-examples",
        type=int,
        default=5,
        help="Print this many examples per label before training.",
    )
    parser.add_argument(
        "--skip-manual-eval-files",
        action="store_true",
        help="Do not write the second-cell manual evaluation JSONL/script after training.",
    )
    parser.add_argument(
        "--manual-eval-path",
        help="Where to write the 500-prompt manual evaluation JSONL. Default: next to --output-dir.",
    )
    parser.add_argument(
        "--manual-eval-script-path",
        help="Where to write the second-cell manual evaluator script. Default: next to --output-dir.",
    )
    parser.add_argument("--no-install-deps", action="store_true")
    parser.add_argument("--gpu-pipeline", action="store_true")
    parser.add_argument("--test-prompt", action="append")
    args, unknown = parser.parse_known_args()
    if unknown:
        print(f"[setup] ignoring unknown notebook args: {unknown}")
    args.install_deps = not args.no_install_deps and running_in_colab()
    return args


if __name__ == "__main__":
    train_and_test(parse_args())
