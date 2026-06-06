#!/usr/bin/env python3
"""Train Syntra's second NLU model for slot extraction.

Input is canonical JSONL:

    {
      "user_message": "Study for CSE 369 Thursday from 7 PM to 9 PM",
      "tool": "add_calendar_block",
      "slots": {
        "title": "Study for CSE 369",
        "date": "Thursday",
        "start_time": "7 PM",
        "end_time": "9 PM"
      },
      "needs_followup": false,
      "missing_slots": [],
      "followup_question": null
    }

The trained token-classification model is saved under ``slot_model`` inside
the intent-model directory. Runtime rules still normalize dates/times and
verify required slots before any tool executes.
"""

from __future__ import annotations

import argparse
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SUPPORTED_SLOT_KEYS = (
    "title",
    "date",
    "start_time",
    "end_time",
    "duration",
    "deadline",
    "course",
)
SLOT_LABELS = ["O"] + [
    label
    for key in SUPPORTED_SLOT_KEYS
    for label in (f"B-{key.upper()}", f"I-{key.upper()}")
]


@dataclass(frozen=True)
class StructuredNluExample:
    user_message: str
    tool: str
    slots: dict[str, str]
    needs_followup: bool
    missing_slots: tuple[str, ...]
    followup_question: str | None


def load_examples(path: Path) -> list[StructuredNluExample]:
    examples: list[StructuredNluExample] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            raw = json.loads(line)
            message = str(raw.get("user_message") or "").strip()
            tool = str(raw.get("tool") or "").strip()
            raw_slots = raw.get("slots") if isinstance(raw.get("slots"), dict) else {}
            slots = {
                str(key): str(value).strip()
                for key, value in raw_slots.items()
                if key in SUPPORTED_SLOT_KEYS and str(value).strip()
            }
            missing = tuple(str(value) for value in raw.get("missing_slots") or [])
            if not message or not tool:
                raise ValueError(
                    f"{path}:{line_number} requires user_message and tool"
                )
            examples.append(
                StructuredNluExample(
                    user_message=message,
                    tool=tool,
                    slots=slots,
                    needs_followup=bool(raw.get("needs_followup")),
                    missing_slots=missing,
                    followup_question=(
                        str(raw["followup_question"]).strip()
                        if raw.get("followup_question")
                        else None
                    ),
                )
            )
    if not examples:
        raise ValueError(f"No structured NLU examples found in {path}")
    return examples


def synthetic_examples() -> list[StructuredNluExample]:
    """Generate clean slot-labeled rows without weak external annotations."""

    rows: list[StructuredNluExample] = []
    titles = [
        "Study for calculus",
        "Review CSE 369",
        "Project meeting",
        "Biology lab prep",
        "Write essay draft",
        "Office hours",
    ]
    dates = ["today", "tomorrow", "Monday", "Thursday", "Friday", "Saturday"]
    ranges = [
        ("9 AM", "10 AM"),
        ("2 PM", "3 PM"),
        ("4 PM", "5:30 PM"),
        ("7 PM", "9 PM"),
    ]
    for title in titles:
        for date_value in dates:
            for start_time, end_time in ranges:
                message = f"Add {title} {date_value} from {start_time} to {end_time}"
                rows.append(
                    StructuredNluExample(
                        user_message=message,
                        tool="add_calendar_block",
                        slots={
                            "title": title,
                            "date": date_value,
                            "start_time": start_time,
                            "end_time": end_time,
                        },
                        needs_followup=False,
                        missing_slots=(),
                        followup_question=None,
                    )
                )
            rows.append(
                StructuredNluExample(
                    user_message=f"Add a calendar block {date_value}",
                    tool="add_calendar_block",
                    slots={"date": date_value},
                    needs_followup=True,
                    missing_slots=("title", "start_time", "end_time"),
                    followup_question=(
                        "What event name, start time, and end time should I use?"
                    ),
                )
            )

    work_items = ["lab 7", "essay draft", "problem set", "project proposal"]
    durations = ["30 minutes", "1 hour", "2 hours"]
    deadlines = ["tomorrow", "Friday", "next week"]
    for title in work_items:
        for duration in durations:
            for deadline in deadlines:
                rows.append(
                    StructuredNluExample(
                        user_message=(
                            f"Schedule {duration} for {title} by {deadline}"
                        ),
                        tool="propose_schedule_change",
                        slots={
                            "title": title,
                            "duration": duration,
                            "deadline": deadline,
                        },
                        needs_followup=False,
                        missing_slots=(),
                        followup_question=None,
                    )
                )

    courses = ["CSE 369", "biology", "calculus", "history"]
    for course in courses:
        for date_value in dates:
            rows.append(
                StructuredNluExample(
                    user_message=f"What {course} homework is due {date_value}?",
                    tool="get_tasks",
                    slots={"course": course, "date": date_value},
                    needs_followup=False,
                    missing_slots=(),
                    followup_question=None,
                )
            )
            rows.append(
                StructuredNluExample(
                    user_message=f"Show my {course} calendar {date_value}",
                    tool="get_calendar_events",
                    slots={"course": course, "date": date_value},
                    needs_followup=False,
                    missing_slots=(),
                    followup_question=None,
                )
            )
    return rows


def dedupe_examples(
    examples: list[StructuredNluExample],
) -> list[StructuredNluExample]:
    by_message: dict[str, StructuredNluExample] = {}
    for example in examples:
        by_message.setdefault(example.user_message.lower(), example)
    return list(by_message.values())


def find_slot_spans(message: str, slots: dict[str, str]) -> list[tuple[int, int, str]]:
    """Return non-overlapping character spans for exact slot values."""

    lower = message.lower()
    candidates: list[tuple[int, int, str]] = []
    for key, value in slots.items():
        start = lower.find(value.lower())
        if start >= 0:
            candidates.append((start, start + len(value), key))

    # Prefer longer spans when title/course values overlap.
    selected: list[tuple[int, int, str]] = []
    for candidate in sorted(candidates, key=lambda item: (-(item[1] - item[0]), item[0])):
        start, end, _ = candidate
        if any(start < other_end and end > other_start for other_start, other_end, _ in selected):
            continue
        selected.append(candidate)
    return sorted(selected)


def align_token_labels(
    offsets: list[tuple[int, int]],
    spans: list[tuple[int, int, str]],
    label_to_id: dict[str, int],
) -> list[int]:
    labels: list[int] = []
    previous_key: str | None = None
    previous_span: tuple[int, int] | None = None
    for token_start, token_end in offsets:
        if token_start == token_end:
            labels.append(-100)
            previous_key = None
            previous_span = None
            continue

        matching = next(
            (
                (span_start, span_end, key)
                for span_start, span_end, key in spans
                if token_start < span_end and token_end > span_start
            ),
            None,
        )
        if matching is None:
            labels.append(label_to_id["O"])
            previous_key = None
            previous_span = None
            continue

        span_start, span_end, key = matching
        prefix = "I" if previous_key == key and previous_span == (span_start, span_end) else "B"
        labels.append(label_to_id[f"{prefix}-{key.upper()}"])
        previous_key = key
        previous_span = (span_start, span_end)
    return labels


def train(args: argparse.Namespace) -> None:
    import numpy as np
    from datasets import Dataset
    from transformers import (
        AutoModelForTokenClassification,
        AutoTokenizer,
        DataCollatorForTokenClassification,
        Trainer,
        TrainingArguments,
    )

    canonical_examples = load_examples(Path(args.data))
    examples = dedupe_examples(canonical_examples + synthetic_examples())
    tokenizer = AutoTokenizer.from_pretrained(args.base_model, use_fast=True)
    label_to_id = {label: index for index, label in enumerate(SLOT_LABELS)}

    rows: list[dict[str, Any]] = []
    skipped_without_spans = 0
    for example in examples:
        encoded = tokenizer(
            example.user_message,
            truncation=True,
            max_length=256,
            return_offsets_mapping=True,
        )
        offsets = [tuple(value) for value in encoded.pop("offset_mapping")]
        spans = find_slot_spans(example.user_message, example.slots)
        if example.slots and not spans:
            skipped_without_spans += 1
        encoded["labels"] = align_token_labels(offsets, spans, label_to_id)
        rows.append(encoded)

    dataset = Dataset.from_list(rows).train_test_split(
        test_size=max(1, int(round(len(rows) * 0.15))),
        seed=args.seed,
    )
    model = AutoModelForTokenClassification.from_pretrained(
        args.base_model,
        num_labels=len(SLOT_LABELS),
        id2label={index: label for index, label in enumerate(SLOT_LABELS)},
        label2id=label_to_id,
    )

    def metrics(eval_pred: Any) -> dict[str, float]:
        logits, labels = eval_pred
        predictions = np.argmax(logits, axis=-1)
        mask = labels != -100
        return {
            "token_accuracy": float((predictions[mask] == labels[mask]).mean())
            if mask.any()
            else 0.0
        }

    kwargs: dict[str, Any] = {
        "output_dir": args.output_dir,
        "learning_rate": args.learning_rate,
        "per_device_train_batch_size": args.batch_size,
        "per_device_eval_batch_size": args.batch_size,
        "num_train_epochs": args.epochs,
        "weight_decay": 0.01,
        "logging_steps": 10,
        "save_strategy": "epoch",
        "report_to": "none",
        "seed": args.seed,
    }
    strategy_key = (
        "eval_strategy"
        if "eval_strategy" in inspect.signature(TrainingArguments.__init__).parameters
        else "evaluation_strategy"
    )
    kwargs[strategy_key] = "epoch"
    trainer_kwargs: dict[str, Any] = {
        "model": model,
        "args": TrainingArguments(**kwargs),
        "train_dataset": dataset["train"],
        "eval_dataset": dataset["test"],
        "data_collator": DataCollatorForTokenClassification(tokenizer=tokenizer),
        "compute_metrics": metrics,
    }
    trainer_parameters = inspect.signature(Trainer.__init__).parameters
    if "processing_class" in trainer_parameters:
        trainer_kwargs["processing_class"] = tokenizer
    elif "tokenizer" in trainer_parameters:
        trainer_kwargs["tokenizer"] = tokenizer

    trainer = Trainer(**trainer_kwargs)
    trainer.train()
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    trainer.save_model(output)
    tokenizer.save_pretrained(output)
    (output / "slot_labels.json").write_text(
        json.dumps({"labels": SLOT_LABELS}, indent=2),
        encoding="utf-8",
    )
    (output / "training_meta.json").write_text(
        json.dumps(
            {
                "structured_examples": len(examples),
                "canonical_examples": len(canonical_examples),
                "rows_without_exact_slot_spans": skipped_without_spans,
                "base_model": args.base_model,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[slot-model] saved to {output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train Syntra NLU slot extractor.")
    parser.add_argument(
        "--data",
        default=str(Path(__file__).with_name("syntra_nlu_training_data.jsonl")),
    )
    parser.add_argument("--output-dir", default="/content/syntra_tool_router/slot_model")
    parser.add_argument("--base-model", default="distilbert-base-uncased")
    parser.add_argument("--epochs", type=float, default=8.0)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=3e-5)
    parser.add_argument("--seed", type=int, default=13)
    return parser.parse_args()


if __name__ == "__main__":
    train(parse_args())
