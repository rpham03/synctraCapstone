"""Regression tests for the standalone NLP tool router."""

from __future__ import annotations

import sys
from collections import Counter
from datetime import date
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_DIR = REPO_ROOT / "tool"
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

from nlp_tool_calling_agent import (
    ADD_CALENDAR_BLOCK_ACTION,
    CLARIFICATION_ACTION,
    MOVE_CALENDAR_BLOCK_ACTION,
    NlpToolCallingAgent,
)
from generate_structured_nlu_dataset import (
    DEFAULT_DATASET_SIZE,
    TEST_RATIO,
    TOOLS,
    TRAIN_RATIO,
    balanced_split_indices,
    build_structured_examples,
)
from one_click_train_nlp_router_colab import (
    TrainingExample,
    select_balanced_dataset,
)
from train_nlu_slot_model import SLOT_LABELS, align_token_labels, find_slot_spans, load_examples


def test_shared_structured_nlu_dataset_has_1000_balanced_examples():
    rows = build_structured_examples()
    counts = Counter(row["tool"] for row in rows)

    assert len(rows) == DEFAULT_DATASET_SIZE == 1000
    assert int(len(rows) * TRAIN_RATIO) == 700
    assert len(rows) - int(len(rows) * TRAIN_RATIO) == 300
    assert TEST_RATIO == 0.30
    assert set(counts) == set(TOOLS)
    assert max(counts.values()) - min(counts.values()) <= 1
    assert len({" ".join(row["user_message"].lower().split()) for row in rows}) == 1000


def test_checked_in_structured_nlu_dataset_matches_generated_1000_rows():
    examples = load_examples(TOOL_DIR / "syntra_nlu_training_data.jsonl")

    assert len(examples) == DEFAULT_DATASET_SIZE
    assert all(
        not example.slots or find_slot_spans(example.user_message, example.slots)
        for example in examples
    )


def test_shared_dataset_split_is_700_300_and_label_balanced():
    rows = build_structured_examples()
    labels = [row["tool"] for row in rows]

    train_indices, test_indices = balanced_split_indices(labels, seed=13)
    train_counts = Counter(labels[index] for index in train_indices)
    test_counts = Counter(labels[index] for index in test_indices)

    assert len(train_indices) == 700
    assert len(test_indices) == 300
    assert set(train_indices).isdisjoint(test_indices)
    assert set(train_counts.values()) == {100}
    assert sorted(test_counts.values()) == [42, 43, 43, 43, 43, 43, 43]


def test_intent_dataset_selection_is_exactly_1000_and_balanced():
    rows = [
        TrainingExample(text=row["user_message"], label=row["tool"])
        for row in build_structured_examples()
    ]

    selected = select_balanced_dataset(rows, DEFAULT_DATASET_SIZE, seed=13)
    counts = Counter(example.label for example in selected)

    assert len(selected) == 1000
    assert max(counts.values()) - min(counts.values()) <= 1


def test_canonical_nlu_data_contains_slots_and_followup_ground_truth():
    examples = load_examples(TOOL_DIR / "syntra_nlu_training_data.jsonl")

    complete = next(
        example
        for example in examples
        if example.user_message == "Study for CSE 369 Thursday from 7 PM to 9 PM"
    )
    incomplete = next(
        example
        for example in examples
        if example.user_message == "Add a calendar block tomorrow"
    )

    assert complete.tool == ADD_CALENDAR_BLOCK_ACTION
    assert complete.slots["start_time"] == "7 PM"
    assert complete.needs_followup is False
    assert incomplete.needs_followup is True
    assert incomplete.missing_slots == ("title", "start_time", "end_time")


def test_slot_training_alignment_builds_bio_labels():
    message = "Study for CSE 369 Thursday from 7 PM to 9 PM"
    spans = find_slot_spans(
        message,
        {
            "title": "Study for CSE 369",
            "date": "Thursday",
            "start_time": "7 PM",
            "end_time": "9 PM",
        },
    )
    offsets = [(0, 5), (6, 9), (10, 13), (14, 17), (18, 26), (32, 33), (34, 36)]
    label_to_id = {label: index for index, label in enumerate(SLOT_LABELS)}

    labels = [
        SLOT_LABELS[index]
        for index in align_token_labels(offsets, spans, label_to_id)
    ]

    assert labels[:4] == ["B-TITLE", "I-TITLE", "I-TITLE", "I-TITLE"]
    assert labels[4] == "B-DATE"
    assert labels[-2:] == ["B-START_TIME", "I-START_TIME"]


def test_greeting_routes_to_ai_agent_without_trained_model():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    call = agent.plan("hi")[0]

    assert call.name == "ai_agent"
    assert call.arguments["message"] == "hi"


def test_move_study_block_routes_before_trained_model():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    class WrongIntentModel:
        def predict(self, message: str) -> tuple[str, float]:
            return "find_free_slots", 0.99

    agent.intent_model = WrongIntentModel()  # type: ignore[assignment]

    call = agent.plan("Move my study block to Friday")[0]

    assert call.name == MOVE_CALENDAR_BLOCK_ACTION
    assert call.arguments == {
        "title_query": "study block",
        "target_date": "2026-06-05",
    }


def test_move_study_block_without_target_date_asks_followup():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    call = agent.plan("Move my study block")[0]

    assert call.name == CLARIFICATION_ACTION
    assert call.arguments["predicted_tool"] == MOVE_CALENDAR_BLOCK_ACTION
    assert call.arguments["missing_slots"] == ["date"]


def test_move_followup_title_is_used_when_multiple_blocks_exist():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    call = agent.plan(
        "Move my study block to Friday CSE 369 review",
        clarification_pending=True,
    )[0]

    assert call.name == MOVE_CALENDAR_BLOCK_ACTION
    assert call.arguments["title_query"] == "CSE 369 review"


def test_emotional_support_routes_to_ai_agent_without_trained_model():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    call = agent.plan("i feel stressed")[0]

    assert call.name == "ai_agent"
    assert call.arguments["message"] == "i feel stressed"


def test_plan_this_week_asks_for_calendar_block_details_without_trained_model():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    call = agent.plan("plan this week")[0]

    assert call.name == CLARIFICATION_ACTION
    assert call.arguments["predicted_tool"] == ADD_CALENDAR_BLOCK_ACTION
    assert "event name" in call.arguments["question"]
    assert "date" in call.arguments["question"]
    assert "start and end time" in call.arguments["question"]


def test_plan_today_asks_for_event_name_and_time_without_trained_model():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    call = agent.plan("plan today")[0]

    assert call.name == CLARIFICATION_ACTION
    assert call.arguments["predicted_tool"] == ADD_CALENDAR_BLOCK_ACTION
    assert "event name" in call.arguments["question"]
    assert "date" not in call.arguments["question"]
    assert "start and end time" in call.arguments["question"]


def test_plan_weekend_asks_for_exact_date_without_trained_model():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    call = agent.plan("plan weekend")[0]

    assert call.name == CLARIFICATION_ACTION
    assert call.arguments["predicted_tool"] == ADD_CALENDAR_BLOCK_ACTION
    assert "event name" in call.arguments["question"]
    assert "date" in call.arguments["question"]
    assert "start and end time" in call.arguments["question"]


def test_incomplete_calendar_block_asks_for_details_without_trained_model():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    call = agent.plan("add a block to my calendar tomorrow")[0]

    assert call.name == CLARIFICATION_ACTION
    assert call.arguments["predicted_tool"] == ADD_CALENDAR_BLOCK_ACTION
    assert "event name" in call.arguments["question"]
    assert "start and end time" in call.arguments["question"]


def test_incomplete_calendar_block_with_a_asks_for_event_name():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    call = agent.plan("add a calendar block tomorrow from 2 pm to 3 pm")[0]

    assert call.name == CLARIFICATION_ACTION
    assert call.arguments["predicted_tool"] == ADD_CALENDAR_BLOCK_ACTION
    assert "event name" in call.arguments["question"]
    assert "start and end time" not in call.arguments["question"]
    assert call.arguments["needs_followup"] is True
    assert call.arguments["missing_slots"] == ["title"]


def test_complete_calendar_block_routes_to_add_block_without_trained_model():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    call = agent.plan(
        "add calendar block study for math tomorrow from 2 PM to 3 PM"
    )[0]

    assert call.name == ADD_CALENDAR_BLOCK_ACTION
    assert call.arguments == {
        "title": "study for math",
        "start_time": "2026-06-04T14:00:00",
        "end_time": "2026-06-04T15:00:00",
    }


def test_complete_plan_request_routes_to_add_block_without_trained_model():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    call = agent.plan("plan study for math tomorrow from 2 PM to 3 PM")[0]

    assert call.name == ADD_CALENDAR_BLOCK_ACTION
    assert call.arguments == {
        "title": "study for math",
        "start_time": "2026-06-04T14:00:00",
        "end_time": "2026-06-04T15:00:00",
    }


def test_clarification_reply_with_details_routes_to_add_block():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    call = agent.plan("study for cse 369 on thursday 4th at 7pm to 9 pm")[0]

    assert call.name == ADD_CALENDAR_BLOCK_ACTION
    assert call.arguments == {
        "title": "study for cse 369",
        "start_time": "2026-06-04T19:00:00",
        "end_time": "2026-06-04T21:00:00",
    }


def test_learned_slots_improve_calendar_block_title_extraction():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    class FakeSlotModel:
        def predict(self, message: str) -> dict[str, str]:
            return {
                "title": "Deep work",
                "date": "Thursday",
                "start_time": "7 PM",
                "end_time": "9 PM",
            }

    agent.slot_model = FakeSlotModel()  # type: ignore[assignment]

    call = agent.plan("Reserve deep focus Thursday from 7 PM to 9 PM")[0]

    assert call.name == ADD_CALENDAR_BLOCK_ACTION
    assert call.arguments == {
        "title": "Deep work",
        "start_time": "2026-06-04T19:00:00",
        "end_time": "2026-06-04T21:00:00",
    }


def test_learned_slots_cannot_create_calendar_block_without_prompt_evidence():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    class HallucinatingSlotModel:
        def predict(self, message: str) -> dict[str, str]:
            return {
                "title": "Invented event",
                "date": "Thursday",
                "start_time": "7 PM",
                "end_time": "9 PM",
            }

    agent.slot_model = HallucinatingSlotModel()  # type: ignore[assignment]

    call = agent.plan("tell me a joke")[0]

    assert call.name == "ai_agent"


def test_calendar_block_with_end_before_start_asks_for_correction():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    call = agent.plan("add study thursday from 9 pm to 7 pm")[0]

    assert call.name == CLARIFICATION_ACTION
    assert call.arguments["missing_slots"] == ["end_time"]
    assert "end time must be after" in call.arguments["question"].lower()


def test_clarification_reply_with_details_overrides_schedule_prediction():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    class FakeIntentModel:
        def predict(self, message: str) -> tuple[str, float]:
            return "propose_schedule_change", 0.99

    agent.intent_model = FakeIntentModel()  # type: ignore[assignment]

    call = agent.plan("study for cse 369 on thursday 4th at 7pm to 9 pm")[0]

    assert call.name == ADD_CALENDAR_BLOCK_ACTION


def test_specific_schedule_request_still_routes_to_schedule_proposal():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    call = agent.plan("schedule 2 hours for homework by Friday")[0]

    assert call.name == "propose_schedule_change"
    assert call.arguments["estimated_minutes"] == 120


def test_incomplete_schedule_request_asks_for_missing_duration():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    call = agent.plan("schedule time for lab 7 by Friday")[0]

    assert call.name == CLARIFICATION_ACTION
    assert call.arguments["predicted_tool"] == "propose_schedule_change"
    assert call.arguments["missing_slots"] == ["duration"]
    assert "duration" in call.arguments["question"].lower()


def test_calendar_block_overrides_trained_calendar_prediction():
    agent = NlpToolCallingAgent(today=date(2026, 6, 3))

    class FakeIntentModel:
        def predict(self, message: str) -> tuple[str, float]:
            return "get_calendar_events", 0.99

    agent.intent_model = FakeIntentModel()  # type: ignore[assignment]

    call = agent.plan("plan study for math tomorrow from 2 PM to 3 PM")[0]

    assert call.name == ADD_CALENDAR_BLOCK_ACTION
