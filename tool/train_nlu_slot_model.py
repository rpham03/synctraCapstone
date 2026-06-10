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

By default this trainer requires the shared 5,000-row structured dataset and
uses a deterministic 70% training / 30% testing split.
"""

from __future__ import annotations

import argparse
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from generate_structured_nlu_dataset import (
    DEFAULT_DATASET_SIZE,
    TEST_RATIO,
    balanced_split_indices,
)
from training_metrics import (
    benchmark_model,
    model_information,
    text_fingerprint,
    token_classification_report,
    write_json,
)


SUPPORTED_SLOT_KEYS = (
    "title",
    "date",
    "start_time",
    "end_time",
    "duration",
    "deadline",
    "course",
    "period",
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
    from datasets import Dataset, DatasetDict
    from transformers import (
        AutoModelForTokenClassification,
        AutoTokenizer,
        DataCollatorForTokenClassification,
        Trainer,
        TrainingArguments,
    )

    canonical_examples = load_examples(Path(args.data))
    examples = dedupe_examples(canonical_examples)
    if args.dataset_size > 0 and len(examples) != args.dataset_size:
        raise ValueError(
            f"Slot dataset has {len(examples)} unique examples; "
            f"expected exactly {args.dataset_size}. Regenerate it with "
            "tool/generate_structured_nlu_dataset.py."
        )
    if not 0 < args.test_ratio < 1:
        raise ValueError("--test-ratio must be between 0 and 1")

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

    full_dataset = Dataset.from_list(rows)
    train_indices, test_indices = balanced_split_indices(
        [example.tool for example in examples],
        train_ratio=1 - args.test_ratio,
        seed=args.seed,
    )
    dataset = DatasetDict(
        {
            "train": full_dataset.select(train_indices),
            "test": full_dataset.select(test_indices),
        }
    )
    print(
        f"[slot-model] split: {len(dataset['train'])} training / "
        f"{len(dataset['test'])} testing"
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
    train_result = trainer.train()
    prediction_output = trainer.predict(dataset["test"])
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    trainer.save_model(output)
    tokenizer.save_pretrained(output)
    (output / "slot_labels.json").write_text(
        json.dumps({"labels": SLOT_LABELS}, indent=2),
        encoding="utf-8",
    )
    predicted = np.argmax(prediction_output.predictions, axis=-1)
    expected = np.asarray(prediction_output.label_ids)
    true_sequences: list[list[int]] = []
    predicted_sequences: list[list[int]] = []
    for expected_row, predicted_row in zip(expected, predicted):
        mask = expected_row != -100
        true_sequences.append(expected_row[mask].astype(int).tolist())
        predicted_sequences.append(predicted_row[mask].astype(int).tolist())
    report = token_classification_report(
        true_sequences,
        predicted_sequences,
        SLOT_LABELS,
    )
    held_out_messages = [examples[index].user_message for index in test_indices]
    report.update(
        {
            "report_type": "trained_slot_extractor_held_out_test",
            "split": {
                "seed": args.seed,
                "train_ratio": round(1 - args.test_ratio, 6),
                "test_ratio": args.test_ratio,
                "total_examples": len(examples),
                "train_examples": len(dataset["train"]),
                "test_examples": len(dataset["test"]),
                "train_text_sha256": text_fingerprint(
                    [examples[index].user_message for index in train_indices]
                ),
                "test_text_sha256": text_fingerprint(held_out_messages),
            },
            "training": {
                "epochs": args.epochs,
                "batch_size": args.batch_size,
                "learning_rate": args.learning_rate,
                "weight_decay": kwargs["weight_decay"],
                "max_sequence_length": 256,
                "train_runtime_seconds": train_result.metrics.get("train_runtime"),
                "train_samples_per_second": train_result.metrics.get(
                    "train_samples_per_second"
                ),
                "train_steps_per_second": train_result.metrics.get(
                    "train_steps_per_second"
                ),
                "train_loss": train_result.metrics.get("train_loss"),
                "eval_loss": prediction_output.metrics.get(
                    "test_loss", prediction_output.metrics.get("eval_loss")
                ),
                "eval_runtime_seconds": prediction_output.metrics.get(
                    "test_runtime", prediction_output.metrics.get("eval_runtime")
                ),
                "eval_samples_per_second": prediction_output.metrics.get(
                    "test_samples_per_second",
                    prediction_output.metrics.get("eval_samples_per_second"),
                ),
                "rows_without_exact_slot_spans": skipped_without_spans,
            },
            "model": model_information(
                model,
                output,
                base_model=args.base_model,
                task="BIO token classification for NLU slot extraction",
            ),
            "latency": benchmark_model(model, tokenizer, held_out_messages),
            "training_history": trainer.state.log_history,
        }
    )
    write_json(output / "slot_metrics.json", report)
    write_json(
        output / "training_meta.json",
        {
            "structured_examples": len(examples),
            "canonical_examples": len(canonical_examples),
            "train_examples": len(dataset["train"]),
            "test_examples": len(dataset["test"]),
            "test_ratio": args.test_ratio,
            "seed": args.seed,
            "rows_without_exact_slot_spans": skipped_without_spans,
            "base_model": args.base_model,
            "entity_micro_f1": report["entity_micro"]["f1"],
            "exact_sequence_accuracy": report["exact_sequence_accuracy"],
            "metrics_artifact": "slot_metrics.json",
        },
    )
    print("\n[slot-metrics] real held-out token-classifier results")
    print(
        json.dumps(
            {
                "entity_micro": report["entity_micro"],
                "entity_macro_f1": report["entity_macro_f1"],
                "exact_sequence_accuracy": report["exact_sequence_accuracy"],
                "token_accuracy_including_o": report["token_accuracy_including_o"],
                "non_o_token_accuracy": report["non_o_token_accuracy"],
                "parameters": report["model"]["total_parameters"],
                "artifact_size_mb": report["model"]["saved_artifact_size_mb"],
                "latency": report["latency"],
            },
            indent=2,
        )
    )
    print("\n[slot-metrics] per-slot held-out entity metrics")
    print(f"{'slot':18} {'precision':>9} {'recall':>8} {'f1':>8} {'support':>8}")
    for slot, row in report["per_slot"].items():
        print(
            f"{slot:18} {row['precision']:>9.4f} {row['recall']:>8.4f} "
            f"{row['f1']:>8.4f} {row['support']:>8}"
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
    parser.add_argument("--dataset-size", type=int, default=DEFAULT_DATASET_SIZE)
    parser.add_argument("--test-ratio", type=float, default=TEST_RATIO)
    return parser.parse_args()


if __name__ == "__main__":
    train(parse_args())
