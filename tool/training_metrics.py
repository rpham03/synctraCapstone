"""Metrics and benchmark helpers shared by the Colab NLU trainers."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import platform
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any


def _safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def _round(value: float) -> float:
    return round(float(value), 6)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def classification_report(
    true_ids: list[int],
    predicted_ids: list[int],
    label_names: list[str],
    confidences: list[float] | None = None,
) -> dict[str, Any]:
    """Return overall, per-label, confusion, and confidence metrics."""

    size = len(label_names)
    total_examples = len(true_ids)
    confusion = [[0 for _ in range(size)] for _ in range(size)]
    for expected, predicted in zip(true_ids, predicted_ids):
        confusion[expected][predicted] += 1

    per_label: dict[str, dict[str, Any]] = {}
    for index, label in enumerate(label_names):
        tp = confusion[index][index]
        support = sum(confusion[index])
        predicted_count = sum(row[index] for row in confusion)
        fp = predicted_count - tp
        fn = support - tp
        tn = total_examples - tp - fp - fn
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        f1 = _safe_div(2 * precision * recall, precision + recall)
        per_label[label] = {
            "accuracy": _round(recall),
            "one_vs_rest_accuracy": _round(_safe_div(tp + tn, total_examples)),
            "precision": _round(precision),
            "recall": _round(recall),
            "f1": _round(f1),
            "support": support,
            "predicted": predicted_count,
            "correct": tp,
        }

    total = total_examples
    correct = sum(confusion[index][index] for index in range(size))
    macro = {
        metric: _round(
            sum(float(values[metric]) for values in per_label.values()) / size
        )
        for metric in ("precision", "recall", "f1")
    }
    weighted = {
        metric: _round(
            _safe_div(
                sum(
                    float(values[metric]) * int(values["support"])
                    for values in per_label.values()
                ),
                total,
            )
        )
        for metric in ("precision", "recall", "f1")
    }
    report: dict[str, Any] = {
        "accuracy": _round(_safe_div(correct, total)),
        "correct": correct,
        "total": total,
        "macro_average": macro,
        "weighted_average": weighted,
        "per_tool": per_label,
        "metric_definitions": {
            "per_tool_accuracy": (
                "Correct predictions among held-out examples whose expected label "
                "is that tool; this is mathematically equal to per-tool recall."
            ),
            "one_vs_rest_accuracy": (
                "Binary accuracy treating one tool as positive and all other tools "
                "as negative."
            ),
            "precision": "Correct predictions for a tool divided by all predictions of that tool.",
            "recall": "Correct predictions for a tool divided by all expected examples of that tool.",
            "f1": "Harmonic mean of precision and recall.",
        },
        "confusion_matrix": {
            "labels": label_names,
            "rows_expected_columns_predicted": confusion,
        },
    }
    if confidences is not None and len(confidences) == total:
        report["confidence"] = confidence_report(
            confidences,
            [expected == predicted for expected, predicted in zip(true_ids, predicted_ids)],
        )
    return report


def confidence_report(
    confidences: list[float],
    correctness: list[bool],
    bins: int = 10,
) -> dict[str, Any]:
    """Return confidence distribution and expected calibration error."""

    bin_rows: list[dict[str, Any]] = []
    ece = 0.0
    for index in range(bins):
        lower = index / bins
        upper = (index + 1) / bins
        positions = [
            position
            for position, confidence in enumerate(confidences)
            if confidence >= lower
            and (confidence < upper or (index == bins - 1 and confidence <= upper))
        ]
        if not positions:
            continue
        average_confidence = sum(confidences[position] for position in positions) / len(
            positions
        )
        accuracy = sum(1 for position in positions if correctness[position]) / len(
            positions
        )
        ece += abs(accuracy - average_confidence) * len(positions) / len(confidences)
        bin_rows.append(
            {
                "range": [round(lower, 2), round(upper, 2)],
                "count": len(positions),
                "average_confidence": _round(average_confidence),
                "accuracy": _round(accuracy),
            }
        )
    correct_confidence = [
        confidence
        for confidence, is_correct in zip(confidences, correctness)
        if is_correct
    ]
    incorrect_confidence = [
        confidence
        for confidence, is_correct in zip(confidences, correctness)
        if not is_correct
    ]
    return {
        "average": _round(sum(confidences) / len(confidences)) if confidences else 0.0,
        "minimum": _round(min(confidences)) if confidences else 0.0,
        "p10": _round(_percentile(confidences, 0.10)),
        "p50": _round(_percentile(confidences, 0.50)),
        "p90": _round(_percentile(confidences, 0.90)),
        "average_when_correct": _round(
            _safe_div(sum(correct_confidence), len(correct_confidence))
        ),
        "average_when_incorrect": _round(
            _safe_div(sum(incorrect_confidence), len(incorrect_confidence))
        ),
        "expected_calibration_error": _round(ece),
        "bins": bin_rows,
    }


def token_classification_report(
    true_sequences: list[list[int]],
    predicted_sequences: list[list[int]],
    label_names: list[str],
) -> dict[str, Any]:
    """Return token and exact BIO entity metrics for the held-out slot split."""

    flat_true: list[int] = []
    flat_predicted: list[int] = []
    exact_sequences = 0
    for expected, predicted in zip(true_sequences, predicted_sequences):
        flat_true.extend(expected)
        flat_predicted.extend(predicted)
        exact_sequences += int(expected == predicted)

    o_id = label_names.index("O")
    non_o_positions = [
        index for index, expected in enumerate(flat_true) if expected != o_id
    ]
    token_accuracy = _safe_div(
        sum(
            1
            for expected, predicted in zip(flat_true, flat_predicted)
            if expected == predicted
        ),
        len(flat_true),
    )
    non_o_accuracy = _safe_div(
        sum(
            1
            for index in non_o_positions
            if flat_true[index] == flat_predicted[index]
        ),
        len(non_o_positions),
    )

    true_entities = [
        _bio_entities(sequence, label_names) for sequence in true_sequences
    ]
    predicted_entities = [
        _bio_entities(sequence, label_names) for sequence in predicted_sequences
    ]
    slot_names = sorted(
        {
            label.split("-", 1)[1].lower()
            for label in label_names
            if label != "O" and "-" in label
        }
    )
    per_slot: dict[str, dict[str, Any]] = {}
    total_tp = total_fp = total_fn = 0
    for slot in slot_names:
        tp = fp = fn = 0
        for expected, predicted in zip(true_entities, predicted_entities):
            expected_slot = {entity for entity in expected if entity[0] == slot}
            predicted_slot = {entity for entity in predicted if entity[0] == slot}
            tp += len(expected_slot & predicted_slot)
            fp += len(predicted_slot - expected_slot)
            fn += len(expected_slot - predicted_slot)
        precision = _safe_div(tp, tp + fp)
        recall = _safe_div(tp, tp + fn)
        per_slot[slot] = {
            "precision": _round(precision),
            "recall": _round(recall),
            "f1": _round(_safe_div(2 * precision * recall, precision + recall)),
            "support": tp + fn,
            "predicted": tp + fp,
            "correct": tp,
        }
        total_tp += tp
        total_fp += fp
        total_fn += fn

    precision = _safe_div(total_tp, total_tp + total_fp)
    recall = _safe_div(total_tp, total_tp + total_fn)
    macro_f1 = _safe_div(
        sum(float(row["f1"]) for row in per_slot.values()), len(per_slot)
    )
    return {
        "token_accuracy_including_o": _round(token_accuracy),
        "non_o_token_accuracy": _round(non_o_accuracy),
        "exact_sequence_accuracy": _round(
            _safe_div(exact_sequences, len(true_sequences))
        ),
        "entity_micro": {
            "precision": _round(precision),
            "recall": _round(recall),
            "f1": _round(_safe_div(2 * precision * recall, precision + recall)),
            "correct": total_tp,
            "false_positive": total_fp,
            "false_negative": total_fn,
        },
        "entity_macro_f1": _round(macro_f1),
        "per_slot": per_slot,
        "test_sequences": len(true_sequences),
        "evaluated_tokens": len(flat_true),
        "slot_tokens": len(non_o_positions),
    }


def _bio_entities(sequence: list[int], label_names: list[str]) -> set[tuple[str, int, int]]:
    entities: set[tuple[str, int, int]] = set()
    current_slot: str | None = None
    current_start = 0
    for index in range(len(sequence) + 1):
        label = label_names[sequence[index]] if index < len(sequence) else "O"
        prefix, slot = (label.split("-", 1) + [""])[:2] if label != "O" else ("O", "")
        if current_slot is not None and (prefix != "I" or slot.lower() != current_slot):
            entities.add((current_slot, current_start, index))
            current_slot = None
        if prefix == "B" or (prefix == "I" and current_slot is None):
            current_slot = slot.lower()
            current_start = index
    return entities


def benchmark_model(
    model: Any,
    tokenizer: Any,
    texts: list[str],
    *,
    max_samples: int = 200,
    warmup_samples: int = 10,
    max_length: int = 256,
) -> dict[str, Any]:
    """Measure single-prompt latency on the model's current device."""

    import torch

    selected = texts[:max_samples]
    if not selected:
        return {"samples": 0}
    device = next(model.parameters()).device
    model.eval()

    def infer(text: str) -> None:
        encoded = tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=max_length,
        )
        encoded = {
            key: value.to(device) if torch.is_tensor(value) else value
            for key, value in encoded.items()
        }
        with torch.inference_mode():
            model(**encoded)
        if device.type == "cuda":
            torch.cuda.synchronize(device)

    for text in selected[:warmup_samples]:
        infer(text)

    latencies_ms: list[float] = []
    started = time.perf_counter()
    for text in selected:
        item_started = time.perf_counter()
        infer(text)
        latencies_ms.append((time.perf_counter() - item_started) * 1000)
    elapsed = time.perf_counter() - started
    return {
        "measurement": "single_prompt_tokenization_plus_model_forward_pass",
        "device": str(device),
        "batch_size": 1,
        "max_sequence_length": max_length,
        "warmup_samples": min(warmup_samples, len(selected)),
        "samples": len(selected),
        "mean_ms": _round(sum(latencies_ms) / len(latencies_ms)),
        "p50_ms": _round(_percentile(latencies_ms, 0.50)),
        "p95_ms": _round(_percentile(latencies_ms, 0.95)),
        "p99_ms": _round(_percentile(latencies_ms, 0.99)),
        "min_ms": _round(min(latencies_ms)),
        "max_ms": _round(max(latencies_ms)),
        "throughput_prompts_per_second": _round(_safe_div(len(selected), elapsed)),
    }


def model_information(
    model: Any,
    model_dir: Path,
    *,
    base_model: str,
    task: str,
) -> dict[str, Any]:
    import torch
    import transformers

    total_parameters = sum(parameter.numel() for parameter in model.parameters())
    trainable_parameters = sum(
        parameter.numel() for parameter in model.parameters() if parameter.requires_grad
    )
    # Count deployable model/tokenizer files, not reports, Trainer checkpoints,
    # or nested companion models saved under the same output directory.
    report_files = {
        "intent_metrics.json",
        "intent_confusion_matrix.csv",
        "intent_test_predictions.jsonl",
        "model_metrics_summary.json",
        "slot_metrics.json",
        "training_meta.json",
    }
    artifact_files = sorted(
        (
            path
            for path in model_dir.iterdir()
            if path.is_file() and path.name not in report_files
        ),
        key=lambda path: path.name,
    )
    model_bytes = sum(path.stat().st_size for path in artifact_files)
    first_parameter = next(model.parameters())
    gpu_name = torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
    gpu_memory = (
        int(torch.cuda.get_device_properties(0).total_memory)
        if torch.cuda.is_available()
        else None
    )
    return {
        "task": task,
        "architecture": model.__class__.__name__,
        "base_model": base_model,
        "total_parameters": total_parameters,
        "trainable_parameters": trainable_parameters,
        "parameter_memory_fp32_mb": _round(total_parameters * 4 / 1024 / 1024),
        "saved_artifact_size_mb": _round(model_bytes / 1024 / 1024),
        "saved_artifact_files": [path.name for path in artifact_files],
        "dtype": str(first_parameter.dtype),
        "device": str(first_parameter.device),
        "python_version": sys.version.split()[0],
        "platform": platform.platform(),
        "torch_version": torch.__version__,
        "transformers_version": transformers.__version__,
        "cuda_available": torch.cuda.is_available(),
        "cuda_version": torch.version.cuda,
        "gpu_name": gpu_name,
        "gpu_memory_mb": _round(gpu_memory / 1024 / 1024) if gpu_memory else None,
    }


def write_confusion_csv(path: Path, labels: list[str], matrix: list[list[int]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["expected\\predicted", *labels])
        for label, row in zip(labels, matrix):
            writer.writerow([label, *row])


def directory_size_bytes(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding="utf-8")


def label_counts(labels: list[str]) -> dict[str, int]:
    return dict(sorted(Counter(labels).items()))


def text_fingerprint(texts: list[str]) -> str:
    """Return a stable SHA-256 fingerprint for an ordered text split."""

    digest = hashlib.sha256()
    for text in texts:
        digest.update(text.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()
