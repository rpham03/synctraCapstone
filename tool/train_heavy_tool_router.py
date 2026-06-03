#!/usr/bin/env python3
"""Train a heavier NLP model for Syntra tool routing.

This script downloads an online function-calling dataset from Hugging Face,
adds Syntra-specific examples for your app tools, and fine-tunes a transformer
sequence classifier.

Default online dataset:
    Salesforce/xlam-function-calling-60k

Install:
    pip install -r tool/tool_router_training_requirements.txt

Train:
    python tool/train_heavy_tool_router.py --max-online-rows 20000 --epochs 2

Use the trained model:
    python tool/nlp_tool_calling_agent.py \
      --model-dir tool/models/syntra_tool_router \
      "when am I free tomorrow"
"""

from __future__ import annotations

import argparse
import csv
import inspect
import json
import random
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


LABELS = [
    "get_assignments",
    "find_free_slots",
    "get_calendar_events",
    "get_tasks",
    "propose_schedule_change",
    "ai_agent",
]


@dataclass(frozen=True)
class TrainingExample:
    text: str
    label: str


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
    return rows


def extract_user_text(row: dict[str, Any]) -> str | None:
    """Best-effort extraction across common function-calling dataset formats."""
    for key in (
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
            for message in value:
                if not isinstance(message, dict):
                    continue
                role = str(message.get("role") or message.get("from") or "").lower()
                if role in {"user", "human"}:
                    content = message.get("content") or message.get("value")
                    if isinstance(content, str) and content.strip():
                        return content.strip()

    raw_json = row.get("json")
    if isinstance(raw_json, str):
        try:
            parsed = json.loads(raw_json)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            return extract_user_text(parsed)

    return None


def normalize_label(value: object) -> str | None:
    """Map dataset labels/tool names to Syntra labels when possible."""
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text:
        return None
    key = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    if key in LABELS:
        return key

    if "canvas" in key and any(word in key for word in ("assignment", "homework", "due")):
        return "get_assignments"
    if any(word in key for word in ("free", "available", "availability", "slot")):
        return "find_free_slots"
    if any(word in key for word in ("calendar", "event", "meeting", "class", "lecture")):
        return "get_calendar_events"
    if any(word in key for word in ("homework", "assignment", "deadline", "task", "todo", "due")):
        return "get_tasks"
    if any(word in key for word in ("schedule_change", "study_block", "plan_study", "propose")):
        return "propose_schedule_change"
    if any(word in key for word in ("out_of_scope", "oos", "general", "chat", "fallback")):
        return "ai_agent"
    return None


def extract_label(row: dict[str, Any]) -> str | None:
    """Best-effort label extraction for local JSON/CSV datasets."""
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

    for key in ("tool_call", "function_call", "api_call"):
        value = row.get(key)
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except json.JSONDecodeError:
                label = normalize_label(value)
                if label:
                    return label
        if isinstance(value, dict):
            label = normalize_label(value.get("name") or value.get("tool"))
            if label:
                return label

    return None


def infer_syntra_label(text: str) -> str:
    lower = text.lower()
    has_schedule_action = any(
        phrase in lower
        for phrase in (
            "schedule",
            "plan",
            "study block",
            "study time",
            "make time",
            "work on",
        )
    )
    has_work_item = any(
        word in lower
        for word in ("homework", "assignment", "task", "exam", "quiz", "lab", "project")
    )
    if has_schedule_action and has_work_item:
        return "propose_schedule_change"
    if any(
        phrase in lower
        for phrase in (
            "free time",
            "open time",
            "availability",
            "available",
            "free slot",
            "when am i free",
            "when can i",
        )
    ):
        return "find_free_slots"
    if "canvas" in lower and any(
        word in lower for word in ("assignment", "homework", "due", "deadline", "sync")
    ):
        return "get_assignments"
    if any(
        word in lower
        for word in (
            "calendar",
            "class",
            "classes",
            "event",
            "meeting",
            "lecture",
            "section",
            "my schedule",
        )
    ):
        return "get_calendar_events"
    if any(
        word in lower
        for word in (
            "task",
            "homework",
            "hw",
            "assignment",
            "due",
            "deadline",
            "quiz",
            "exam",
            "project",
            "lab",
            "todo",
        )
    ):
        return "get_tasks"
    return "ai_agent"


def _rows_from_json_value(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, list):
        for item in value:
            if isinstance(item, dict):
                yield from _rows_from_json_value(item)
        return
    if isinstance(value, dict):
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
                if isinstance(frames, list) and frames:
                    first_frame = next((f for f in frames if isinstance(f, dict)), None)
                    if first_frame:
                        row["service"] = first_frame.get("service")
                        state = first_frame.get("state")
                        if isinstance(state, dict):
                            row["active_intent"] = state.get("active_intent")
                yield row
            return

        for key in ("data", "train", "examples", "rows"):
            nested = value.get(key)
            if isinstance(nested, list):
                yield from _rows_from_json_value(nested)
                return
        yield value


def _rows_from_file(path: Path) -> Iterable[dict[str, Any]]:
    suffix = path.suffix.lower()
    if suffix == ".jsonl":
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
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
        yield from _rows_from_json_value(value)
        return

    if suffix == ".parquet":
        try:
            from datasets import load_dataset

            dataset = load_dataset("parquet", data_files=str(path), split="train")
            for row in dataset:
                if isinstance(row, dict):
                    yield dict(row)
            return
        except Exception:
            pass

        try:
            import pandas as pd

            frame = pd.read_parquet(path)
            for row in frame.to_dict(orient="records"):
                if isinstance(row, dict):
                    yield row
        except Exception:
            return
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
                    first, second = line.split(delimiter, 1)
                    label = normalize_label(first)
                    if label:
                        yield {"text": second, "label": label}
                    else:
                        yield {"text": first, "label": normalize_label(second)}
                else:
                    yield {"text": line}


def _is_real_data_file(path: Path) -> bool:
    if "__MACOSX" in path.parts:
        return False
    if path.name.startswith("._"):
        return False
    if path.name.startswith("."):
        return False
    return path.suffix.lower() in {
        ".jsonl",
        ".json",
        ".csv",
        ".txt",
        ".tsv",
        ".parquet",
    }


def _data_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if _is_real_data_file(root) else []
    return [
        path
        for path in root.rglob("*")
        if _is_real_data_file(path)
    ]


def prepare_local_data_path(path: str, extract_dir: str | None) -> Path:
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"local data path not found: {source}")
    if source.suffix.lower() != ".zip":
        return source

    target = Path(extract_dir) if extract_dir else source.with_suffix("")
    target.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as zf:
        for member in zf.infolist():
            member_path = Path(member.filename)
            if "__MACOSX" in member_path.parts or member_path.name.startswith("._"):
                continue
            zf.extract(member, target)
    print(f"extracted {source} -> {target}")
    return target


def load_local_examples(path: str, *, extract_dir: str | None = None) -> list[TrainingExample]:
    root = prepare_local_data_path(path, extract_dir)
    rows: list[TrainingExample] = []
    data_files = _data_files(root)
    print(f"local data files found: {len(data_files)}")
    for file_path in data_files:
        for raw in _rows_from_file(file_path):
            text = extract_user_text(raw)
            if not text:
                continue
            label = extract_label(raw) or infer_syntra_label(text)
            rows.append(TrainingExample(text=text, label=label))
    return rows


def load_online_examples(
    dataset_name: str,
    *,
    split: str,
    max_rows: int,
    seed: int,
) -> list[TrainingExample]:
    try:
        from datasets import load_dataset
    except ImportError as exc:
        raise RuntimeError(
            "Install training dependencies first: "
            "pip install -r tool/tool_router_training_requirements.txt"
        ) from exc

    dataset = load_dataset(dataset_name, split=split)
    if max_rows > 0 and len(dataset) > max_rows:
        dataset = dataset.shuffle(seed=seed).select(range(max_rows))

    rows: list[TrainingExample] = []
    for raw in dataset:
        if not isinstance(raw, dict):
            continue
        text = extract_user_text(raw)
        if not text:
            continue
        rows.append(TrainingExample(text=text, label=infer_syntra_label(text)))
    return rows


def balance_examples(examples: list[TrainingExample], seed: int) -> list[TrainingExample]:
    by_label: dict[str, list[TrainingExample]] = {label: [] for label in LABELS}
    for ex in examples:
        if ex.label in by_label:
            by_label[ex.label].append(ex)

    max_count = max(len(items) for items in by_label.values())
    balanced: list[TrainingExample] = []
    rng = random.Random(seed)
    for label, items in by_label.items():
        if not items:
            continue
        pool = list(items)
        while len(pool) < max_count:
            pool.append(rng.choice(items))
        balanced.extend(pool[:max_count])
    rng.shuffle(balanced)
    return balanced


def main() -> int:
    parser = argparse.ArgumentParser(description="Train Syntra tool intent router.")
    parser.add_argument(
        "--dataset-name",
        default="Salesforce/xlam-function-calling-60k",
        help=(
            "Hugging Face dataset to download. If you do not have access to "
            "Salesforce/xlam-function-calling-60k, try glaiveai/glaive-function-calling-v2."
        ),
    )
    parser.add_argument("--split", default="train")
    parser.add_argument("--max-online-rows", type=int, default=20000)
    parser.add_argument(
        "--local-data",
        help="Local JSON/JSONL/CSV/TXT/TSV file, directory, or ZIP uploaded to Colab.",
    )
    parser.add_argument(
        "--local-extract-dir",
        help="Where to unzip --local-data when it is a ZIP. Defaults to ZIP name.",
    )
    parser.add_argument(
        "--skip-online",
        action="store_true",
        help="Train only on --local-data plus Syntra synthetic examples.",
    )
    parser.add_argument(
        "--preview-local-data",
        action="store_true",
        help="Load --local-data, print label counts and examples, then exit.",
    )
    parser.add_argument("--base-model", default="microsoft/deberta-v3-base")
    parser.add_argument("--output-dir", default="tool/models/syntra_tool_router")
    parser.add_argument("--epochs", type=float, default=2.0)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--learning-rate", type=float, default=2e-5)
    parser.add_argument("--seed", type=int, default=13)
    parser.add_argument("--no-balance", action="store_true")
    args = parser.parse_args()

    online = []
    if not args.skip_online:
        online = load_online_examples(
            args.dataset_name,
            split=args.split,
            max_rows=args.max_online_rows,
            seed=args.seed,
        )
    local = (
        load_local_examples(args.local_data, extract_dir=args.local_extract_dir)
        if args.local_data
        else []
    )
    examples = online + local + synthetic_examples()
    if not examples:
        raise RuntimeError("No training examples found.")
    if not args.no_balance:
        examples = balance_examples(examples, args.seed)

    if args.preview_local_data:
        counts = {label: 0 for label in LABELS}
        for ex in local:
            counts[ex.label] = counts.get(ex.label, 0) + 1
        print(json.dumps({"local_examples": len(local), "label_counts": counts}, indent=2))
        for ex in local[:20]:
            print(json.dumps({"label": ex.label, "text": ex.text[:240]}, ensure_ascii=False))
        return 0

    try:
        import numpy as np
        from datasets import Dataset
        from transformers import (
            AutoModelForSequenceClassification,
            AutoTokenizer,
            DataCollatorWithPadding,
            Trainer,
            TrainingArguments,
        )
    except ImportError as exc:
        raise RuntimeError(
            "Install training dependencies first: "
            "pip install -r tool/tool_router_training_requirements.txt"
        ) from exc

    label_to_id = {label: idx for idx, label in enumerate(LABELS)}
    rows = {
        "text": [ex.text for ex in examples],
        "label": [label_to_id[ex.label] for ex in examples],
    }
    dataset = Dataset.from_dict(rows).train_test_split(test_size=0.1, seed=args.seed)

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

    output_dir = Path(args.output_dir)
    training_kwargs: dict[str, Any] = {
        "output_dir": str(output_dir),
        "learning_rate": args.learning_rate,
        "per_device_train_batch_size": args.batch_size,
        "per_device_eval_batch_size": args.batch_size,
        "num_train_epochs": args.epochs,
        "weight_decay": 0.01,
        "logging_steps": 50,
        "save_strategy": "epoch",
        "load_best_model_at_end": False,
        "report_to": "none",
        "seed": args.seed,
    }
    strategy_arg = (
        "eval_strategy"
        if "eval_strategy" in inspect.signature(TrainingArguments.__init__).parameters
        else "evaluation_strategy"
    )
    training_kwargs[strategy_arg] = "epoch"
    training_args = TrainingArguments(**training_kwargs)

    trainer_kwargs: dict[str, Any] = {
        "model": model,
        "args": training_args,
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

    output_dir.mkdir(parents=True, exist_ok=True)
    trainer.save_model(output_dir)
    tokenizer.save_pretrained(output_dir)
    (output_dir / "labels.json").write_text(json.dumps({"labels": LABELS}, indent=2))
    (output_dir / "training_meta.json").write_text(
        json.dumps(
            {
                "dataset_name": args.dataset_name,
                "online_examples": len(online),
                "local_examples": len(local),
                "total_examples": len(examples),
                "base_model": args.base_model,
            },
            indent=2,
        )
    )
    print(f"saved model to {output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
