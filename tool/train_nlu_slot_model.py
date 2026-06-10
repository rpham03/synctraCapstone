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
uses its explicit train, development, unseen-template, and human-style splits.
"""

from __future__ import annotations

import argparse
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from generate_structured_nlu_dataset import (
    DATASET_SPLITS,
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
    split: str
    template_family_id: str


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
                    split=str(raw.get("split") or "train"),
                    template_family_id=str(raw.get("template_family_id") or ""),
                )
            )
    if not examples:
        raise ValueError(f"No structured NLU examples found in {path}")
    return examples


def explicit_slot_split_indices(
    examples: list[StructuredNluExample],
) -> dict[str, list[int]] | None:
    if not examples or any(example.split not in DATASET_SPLITS for example in examples):
        return None
    split_indices = {split: [] for split in DATASET_SPLITS}
    for index, example in enumerate(examples):
        split_indices[example.split].append(index)
    if any(not split_indices[split] for split in DATASET_SPLITS):
        return None
    return split_indices


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
    explicit_splits = explicit_slot_split_indices(examples)
    if explicit_splits is not None:
        train_indices = explicit_splits["train"]
        development_indices = explicit_splits["development"]
        test_indices = explicit_splits["unseen_template_test"]
        human_style_indices = explicit_splits["human_style_test"]
        unseen_families = {
            examples[index].template_family_id for index in test_indices
        }
        for split_name, indices in (
            ("train", train_indices),
            ("development", development_indices),
        ):
            overlap = unseen_families & {
                examples[index].template_family_id for index in indices
            }
            if overlap:
                raise ValueError(
                    f"{len(overlap)} unseen-template families leaked into "
                    f"{split_name}"
                )
    else:
        train_indices, test_indices = balanced_split_indices(
            [example.tool for example in examples],
            train_ratio=1 - args.test_ratio,
            seed=args.seed,
        )
        development_indices = test_indices
        human_style_indices = test_indices
    dataset = DatasetDict(
        {
            "train": full_dataset.select(train_indices),
            "test": full_dataset.select(test_indices),
            "development": full_dataset.select(development_indices),
            "human_style_test": full_dataset.select(human_style_indices),
        }
    )
    print(
        f"[slot-model] split: {len(dataset['train'])} training / "
        f"{len(dataset['development'])} development / "
        f"{len(dataset['test'])} unseen-template testing / "
        f"{len(dataset['human_style_test'])} human-style proxy testing"
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
        "eval_dataset": dataset["development"],
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
    unseen_suite_report = dict(report)
    unseen_suite_report["text_sha256"] = text_fingerprint(held_out_messages)

    def evaluate_slot_suite(
        dataset_key: str,
        indices: list[int],
    ) -> dict[str, Any]:
        suite_output = trainer.predict(dataset[dataset_key])
        suite_predicted = np.argmax(suite_output.predictions, axis=-1)
        suite_expected = np.asarray(suite_output.label_ids)
        suite_true_sequences: list[list[int]] = []
        suite_predicted_sequences: list[list[int]] = []
        for expected_row, predicted_row in zip(suite_expected, suite_predicted):
            mask = expected_row != -100
            suite_true_sequences.append(expected_row[mask].astype(int).tolist())
            suite_predicted_sequences.append(predicted_row[mask].astype(int).tolist())
        suite_report = token_classification_report(
            suite_true_sequences,
            suite_predicted_sequences,
            SLOT_LABELS,
        )
        suite_report["text_sha256"] = text_fingerprint(
            [examples[index].user_message for index in indices]
        )
        return suite_report

    evaluation_suites = {
        "development": evaluate_slot_suite("development", development_indices),
        "unseen_template_test": unseen_suite_report,
        "human_style_test": evaluate_slot_suite(
            "human_style_test",
            human_style_indices,
        ),
    }
    report.update(
        {
            "report_type": "trained_slot_extractor_unseen_template_test",
            "split": {
                "seed": args.seed,
                "strategy": (
                    "explicit_four_way_dataset_split"
                    if explicit_splits is not None
                    else "legacy_balanced_random_split"
                ),
                "total_examples": len(examples),
                "train_examples": len(dataset["train"]),
                "development_examples": len(dataset["development"]),
                "unseen_template_test_examples": len(dataset["test"]),
                "human_style_test_examples": len(dataset["human_style_test"]),
                "train_text_sha256": text_fingerprint(
                    [examples[index].user_message for index in train_indices]
                ),
                "development_text_sha256": text_fingerprint(
                    [examples[index].user_message for index in development_indices]
                ),
                "unseen_template_test_text_sha256": text_fingerprint(
                    held_out_messages
                ),
                "human_style_test_text_sha256": text_fingerprint(
                    [examples[index].user_message for index in human_style_indices]
                ),
                "unseen_template_family_overlap_with_train": len(
                    {
                        examples[index].template_family_id for index in train_indices
                    }
                    & {
                        examples[index].template_family_id for index in test_indices
                    }
                ),
                "unseen_template_family_overlap_with_development": len(
                    {
                        examples[index].template_family_id
                        for index in development_indices
                    }
                    & {
                        examples[index].template_family_id for index in test_indices
                    }
                ),
            },
            "evaluation_suites": evaluation_suites,
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
            "development_examples": len(dataset["development"]),
            "unseen_template_test_examples": len(dataset["test"]),
            "human_style_test_examples": len(dataset["human_style_test"]),
            "seed": args.seed,
            "rows_without_exact_slot_spans": skipped_without_spans,
            "base_model": args.base_model,
            "evaluation_entity_micro_f1": {
                name: suite["entity_micro"]["f1"]
                for name, suite in evaluation_suites.items()
            },
            "evaluation_exact_sequence_accuracy": {
                name: suite["exact_sequence_accuracy"]
                for name, suite in evaluation_suites.items()
            },
            "metrics_artifact": "slot_metrics.json",
        },
    )
    print("\n[slot-metrics] real token-classifier results by evaluation suite")
    print(
        json.dumps(
            {
                "evaluation_suites": {
                    name: {
                        "entity_micro_f1": suite["entity_micro"]["f1"],
                        "entity_macro_f1": suite["entity_macro_f1"],
                        "exact_sequence_accuracy": suite["exact_sequence_accuracy"],
                        "non_o_token_accuracy": suite["non_o_token_accuracy"],
                        "examples": suite["test_sequences"],
                    }
                    for name, suite in evaluation_suites.items()
                },
                "parameters": report["model"]["total_parameters"],
                "artifact_size_mb": report["model"]["saved_artifact_size_mb"],
                "latency": report["latency"],
            },
            indent=2,
        )
    )
    print("\n[slot-metrics] per-slot unseen-template entity metrics")
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
    parser.add_argument(
        "--test-ratio",
        type=float,
        default=TEST_RATIO,
        help=(
            "Legacy fallback ratio when input rows lack explicit split metadata. "
            "The canonical dataset uses four fixed splits."
        ),
    )
    return parser.parse_args()


if __name__ == "__main__":
    train(parse_args())
