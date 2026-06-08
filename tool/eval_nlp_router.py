#!/usr/bin/env python3
"""Evaluate intent routing on the held-out 30% test split.

Uses a dependency-free multinomial Naive Bayes classifier as a fast proxy for
the heavy trained router. It won't match the transformer's accuracy, but it
reliably surfaces *which intents are confusable* — exactly where adding training
data (or hard negatives) pays off. Run: `python tool/eval_nlp_router.py`.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Any

from generate_structured_nlu_dataset import (
    balanced_split_indices,
    build_structured_examples,
)

_WORD = re.compile(r"[a-z0-9']+")


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


def train_nb(rows: list[dict[str, Any]], train_idx: list[int]) -> dict[str, Any]:
    class_docs: Counter[str] = Counter()
    word_counts: dict[str, Counter[str]] = defaultdict(Counter)
    vocab: set[str] = set()
    for i in train_idx:
        label = rows[i]["tool"]
        class_docs[label] += 1
        for tok in _tokens(rows[i]["user_message"]):
            word_counts[label][tok] += 1
            vocab.add(tok)
    return {
        "class_docs": class_docs,
        "word_counts": word_counts,
        "vocab_size": len(vocab),
        "total_docs": sum(class_docs.values()),
        "class_total_words": {c: sum(word_counts[c].values()) for c in class_docs},
    }


def predict(model: dict[str, Any], message: str) -> str:
    best, best_score = "", -1e18
    tokens = _tokens(message)
    for label, docs in model["class_docs"].items():
        score = math.log(docs / model["total_docs"])
        denom = model["class_total_words"][label] + model["vocab_size"]
        counts = model["word_counts"][label]
        for tok in tokens:
            score += math.log((counts.get(tok, 0) + 1) / denom)
        if score > best_score:
            best_score, best = score, label
    return best


def evaluate(rows: list[dict[str, Any]] | None = None, *, seed: int = 13) -> dict[str, Any]:
    rows = rows if rows is not None else build_structured_examples()
    train_idx, test_idx = balanced_split_indices([r["tool"] for r in rows], seed=seed)
    model = train_nb(rows, train_idx)

    correct = 0
    per_total: Counter[str] = Counter()
    per_correct: Counter[str] = Counter()
    confusions: Counter[tuple[str, str]] = Counter()
    for i in test_idx:
        true = rows[i]["tool"]
        pred = predict(model, rows[i]["user_message"])
        per_total[true] += 1
        if pred == true:
            correct += 1
            per_correct[true] += 1
        else:
            confusions[(true, pred)] += 1

    return {
        "accuracy": correct / len(test_idx),
        "per_tool": {t: per_correct[t] / per_total[t] for t in per_total},
        "confusions": confusions.most_common(12),
        "train": len(train_idx),
        "test": len(test_idx),
    }


def main() -> None:
    report = evaluate()
    print(f"train/test rows: {report['train']}/{report['test']}")
    print(f"overall accuracy: {report['accuracy']:.3f}\n")
    print("per-tool accuracy (worst first):")
    for tool, acc in sorted(report["per_tool"].items(), key=lambda kv: kv[1]):
        print(f"  {acc:.3f}  {tool}")
    print("\ntop confusions (true -> predicted : count):")
    for (true, pred), count in report["confusions"]:
        print(f"  {true} -> {pred} : {count}")


if __name__ == "__main__":
    main()
