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
    DELETE_CALENDAR_BLOCK_ACTION,
    MOVE_CALENDAR_BLOCK_ACTION,
    NlpToolCallingAgent,
)
from generate_structured_nlu_dataset import (
    DATASET_SPLITS,
    DEFAULT_DATASET_SIZE,
    DEFAULT_SPLIT_COUNTS,
    TEST_RATIO,
    TOOLS,
    TRAIN_SOURCE_MIX,
    TRAIN_RATIO,
    balanced_split_indices,
    build_structured_examples,
    dataset_manifest,
    explicit_split_indices,
)
from one_click_train_nlp_router_colab import (
    TrainingExample,
    select_balanced_dataset,
)
from train_nlu_slot_model import SLOT_LABELS, align_token_labels, find_slot_spans, load_examples


def test_shared_structured_nlu_dataset_has_5000_balanced_examples():
    rows = build_structured_examples()
    counts = Counter(row["tool"] for row in rows)

    assert len(rows) == DEFAULT_DATASET_SIZE == 5000
    assert int(len(rows) * TRAIN_RATIO) == 3500
    assert len(rows) - int(len(rows) * TRAIN_RATIO) == 1500
    assert TEST_RATIO == 0.30
    assert set(counts) == set(TOOLS)
    assert max(counts.values()) - min(counts.values()) <= 1
    assert len({" ".join(row["user_message"].lower().split()) for row in rows}) == 5000


def test_shared_dataset_has_explicit_realistic_evaluation_splits():
    rows = build_structured_examples()
    split_indices = explicit_split_indices(rows)
    manifest = dataset_manifest(rows)

    assert set(split_indices) == set(DATASET_SPLITS)
    assert {name: len(indices) for name, indices in split_indices.items()} == (
        DEFAULT_SPLIT_COUNTS
    )
    assert manifest["unseen_template_family_overlap_with_train"] == 0
    assert manifest["unseen_template_family_overlap_with_development"] == 0
    assert manifest["training_source_mix"] == Counter(
        {
            source: int(round(DEFAULT_SPLIT_COUNTS["train"] * ratio))
            for source, ratio in TRAIN_SOURCE_MIX.items()
        }
    )


def test_realistic_dataset_has_followups_noise_and_human_style_proxy():
    rows = build_structured_examples()

    assert sum(
        row["split"] == "train" and row["needs_followup"] for row in rows
    ) >= 350
    assert any(
        row["split"] == "train" and row["source"] == "noisy_generated"
        for row in rows
    )
    assert all(
        row["source"] == "human_style_proxy"
        for row in rows
        if row["split"] == "human_style_test"
    )


def test_calendar_training_data_uses_general_natural_phrasing():
    rows = build_structured_examples()
    messages = [
        row["user_message"].lower()
        for row in rows
        if row["tool"] == ADD_CALENDAR_BLOCK_ACTION
    ]

    assert any("between" in message for message in messages)
    assert any("starting at" in message and "ending at" in message for message in messages)
    assert any("with a start time" in message for message in messages)
    assert any("could you put" in message for message in messages)


def test_delete_training_data_uses_general_and_multiple_event_phrasing():
    rows = build_structured_examples()
    messages = [
        row["user_message"].lower()
        for row in rows
        if row["tool"] == DELETE_CALENDAR_BLOCK_ACTION
    ]

    assert any(message.startswith("delete ") for message in messages)
    assert any(message.startswith("remove ") for message in messages)
    assert any(message.startswith("cancel ") for message in messages)
    assert any("take " in message and " off my calendar" in message for message in messages)
    assert any(" and " in message for message in messages)
    assert any("every event" in message or "all study blocks" in message for message in messages)


def test_checked_in_structured_nlu_dataset_matches_generated_rows():
    examples = load_examples(TOOL_DIR / "syntra_nlu_training_data.jsonl")

    assert len(examples) == DEFAULT_DATASET_SIZE
    assert Counter(example.split for example in examples) == Counter(
        DEFAULT_SPLIT_COUNTS
    )
    assert all(
        not example.slots or find_slot_spans(example.user_message, example.slots)
        for example in examples
    )


def test_shared_dataset_split_is_3500_1500_and_label_balanced():
    rows = build_structured_examples()
    labels = [row["tool"] for row in rows]

    train_indices, test_indices = balanced_split_indices(labels, seed=13)
    train_counts = Counter(labels[index] for index in train_indices)
    test_counts = Counter(labels[index] for index in test_indices)

    assert len(train_indices) == 3500
    assert len(test_indices) == 1500
    assert set(train_indices).isdisjoint(test_indices)
    assert max(train_counts.values()) - min(train_counts.values()) <= 1
    assert max(test_counts.values()) - min(test_counts.values()) <= 1
    assert set(train_counts) == set(test_counts) == set(TOOLS)


def test_intent_dataset_selection_is_exact_size_and_balanced():
    rows = [
        TrainingExample(text=row["user_message"], label=row["tool"])
        for row in build_structured_examples()
    ]

    selected = select_balanced_dataset(rows, DEFAULT_DATASET_SIZE, seed=13)
    counts = Counter(example.label for example in selected)

    assert len(selected) == 5000
    assert max(counts.values()) - min(counts.values()) <= 1


def test_router_eval_separates_intents_on_held_out_split():
    from eval_nlp_router import evaluate

    report = evaluate()

    assert report["train"] == 3500 and report["test"] == 1500
    assert set(report["per_tool"]) == set(TOOLS)
    # A dependency-free NB proxy should cleanly separate the intents.
    assert report["accuracy"] >= 0.90
    assert min(report["per_tool"].values()) >= 0.70


def test_dataset_teaches_period_slots_for_preferences():
    """Productivity-preference examples carry an extractable period slot."""

    examples = load_examples(TOOL_DIR / "syntra_nlu_training_data.jsonl")
    period_examples = [e for e in examples if e.slots.get("period")]

    assert len(period_examples) >= 100
    assert all(
        find_slot_spans(e.user_message, {"period": e.slots["period"]})
        for e in period_examples
    )


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
        if example.tool == ADD_CALENDAR_BLOCK_ACTION
        and example.slots == {"date": "tomorrow"}
        and example.missing_slots == ("title", "start_time", "end_time")
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


def test_delete_event_routes_before_trained_model_for_flexible_phrasing():
    agent = NlpToolCallingAgent(today=date(2026, 6, 7))

    prompts = {
        "delete my bible study": "bible study",
        "remove the dentist appointment": "dentist appointment",
        "cancel office hours": "office hours",
        "take project meeting off my calendar": "project meeting",
        "get rid of gym from my schedule": "gym",
        "erase my focus block": "focus block",
        "drop advising meeting": "advising meeting",
    }

    for prompt, title in prompts.items():
        call = agent.plan(prompt)[0]
        assert call.name == DELETE_CALENDAR_BLOCK_ACTION
        assert call.arguments["title_queries"] == [title]
        assert call.arguments["delete_all_matches"] is False


def test_delete_multiple_named_events_routes_as_one_call():
    agent = NlpToolCallingAgent(today=date(2026, 6, 7))

    call = agent.plan("Cancel bible study, dentist, and gym")[0]

    assert call.name == DELETE_CALENDAR_BLOCK_ACTION
    assert call.arguments["title_queries"] == ["bible study", "dentist", "gym"]
    assert call.arguments["delete_all_matches"] is False


def test_delete_all_events_on_date_routes_with_date_scope():
    agent = NlpToolCallingAgent(today=date(2026, 6, 7))

    call = agent.plan("Clear every event from my calendar tomorrow")[0]

    assert call.name == DELETE_CALENDAR_BLOCK_ACTION
    assert call.arguments["title_queries"] == []
    assert call.arguments["delete_all_matches"] is True
    assert call.arguments["start_date"] == "2026-06-08"
    assert call.arguments["end_date"] == "2026-06-08"


def test_delete_generic_event_asks_which_event():
    agent = NlpToolCallingAgent(today=date(2026, 6, 7))

    call = agent.plan("Delete an event")[0]

    assert call.name == CLARIFICATION_ACTION
    assert call.arguments["predicted_tool"] == DELETE_CALENDAR_BLOCK_ACTION
    assert call.arguments["missing_slots"] == ["title"]


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


def test_ambiguous_calendar_times_ask_for_am_or_pm():
    agent = NlpToolCallingAgent(today=date(2026, 6, 6))

    call = agent.plan(
        "bible study, the date is tomorrow and the start time is 10:30 to 11:30"
    )[0]

    assert call.name == CLARIFICATION_ACTION
    assert call.arguments["predicted_tool"] == ADD_CALENDAR_BLOCK_ACTION
    assert call.arguments["missing_slots"] == ["time_period"]
    assert "morning" in call.arguments["question"].lower()


def test_morning_resolves_ambiguous_calendar_times_to_am():
    agent = NlpToolCallingAgent(today=date(2026, 6, 6))

    call = agent.plan(
        "bible study, the date is tomorrow and the start time is "
        "10:30 to 11:30 in the morning"
    )[0]

    assert call.name == ADD_CALENDAR_BLOCK_ACTION
    assert call.arguments == {
        "title": "bible study",
        "start_time": "2026-06-07T10:30:00",
        "end_time": "2026-06-07T11:30:00",
    }


def test_evening_resolves_ambiguous_calendar_times_to_pm():
    agent = NlpToolCallingAgent(today=date(2026, 6, 6))

    call = agent.plan("dinner tomorrow from 6 to 7 in the evening")[0]

    assert call.name == ADD_CALENDAR_BLOCK_ACTION
    assert call.arguments == {
        "title": "dinner",
        "start_time": "2026-06-07T18:00:00",
        "end_time": "2026-06-07T19:00:00",
    }


def test_bare_pm_reply_resolves_ambiguous_calendar_times():
    """Answering an AM/PM clarification with a bare 'pm' must resolve, not loop."""

    agent = NlpToolCallingAgent(today=date(2026, 6, 6))

    # Mirrors the backend merge: the original ambiguous request + the user's
    # bare period answer appended at the end (not adjacent to the time).
    call = agent.plan(
        "bible study from 10:30 to 11:30 tomorrow pm",
        clarification_pending=True,
    )[0]

    assert call.name == ADD_CALENDAR_BLOCK_ACTION
    assert call.arguments["start_time"] == "2026-06-07T22:30:00"
    assert call.arguments["end_time"] == "2026-06-07T23:30:00"


def test_calendar_details_without_times_does_not_ask_am_pm():
    """No clock numbers -> never ask AM/PM (that loop is unanswerable)."""

    agent = NlpToolCallingAgent(today=date(2026, 6, 6))

    calls = agent.plan(
        "bible study tomorrow please",
        clarification_pending=True,
    )
    # Must not return an unbreakable time_period clarification.
    for call in calls:
        if call.name == CLARIFICATION_ACTION:
            assert call.arguments.get("missing_slots") != ["time_period"]


def test_calendar_block_accepts_polite_between_phrase():
    agent = NlpToolCallingAgent(today=date(2026, 6, 6))

    call = agent.plan(
        "Could you please put Bible study on my calendar for tomorrow "
        "sometime between 10:30 and 11:30 in the morning?"
    )[0]

    assert call.name == ADD_CALENDAR_BLOCK_ACTION
    assert call.arguments == {
        "title": "Bible study",
        "start_time": "2026-06-07T10:30:00",
        "end_time": "2026-06-07T11:30:00",
    }


def test_calendar_block_accepts_starting_and_ending_phrase():
    agent = NlpToolCallingAgent(today=date(2026, 6, 6))

    call = agent.plan(
        "I need a dentist appointment tomorrow starting at 2 PM and ending at 3 PM"
    )[0]

    assert call.name == ADD_CALENDAR_BLOCK_ACTION
    assert call.arguments == {
        "title": "dentist appointment",
        "start_time": "2026-06-07T14:00:00",
        "end_time": "2026-06-07T15:00:00",
    }


def test_calendar_block_accepts_labeled_times_in_any_order():
    agent = NlpToolCallingAgent(today=date(2026, 6, 6))

    call = agent.plan(
        "Please create exam review for Thursday with a start time of "
        "7 PM and end time of 9 PM"
    )[0]

    assert call.name == ADD_CALENDAR_BLOCK_ACTION
    assert call.arguments == {
        "title": "exam review",
        "start_time": "2026-06-11T19:00:00",
        "end_time": "2026-06-11T21:00:00",
    }


def test_calendar_block_accepts_start_time_plus_duration():
    agent = NlpToolCallingAgent(today=date(2026, 6, 6))

    call = agent.plan("I have a dentist appointment tomorrow at 2 PM for 1 hour")[0]

    assert call.name == ADD_CALENDAR_BLOCK_ACTION
    assert call.arguments == {
        "title": "dentist appointment",
        "start_time": "2026-06-07T14:00:00",
        "end_time": "2026-06-07T15:00:00",
    }


def test_calendar_block_accepts_word_duration_and_time_period_filler():
    agent = NlpToolCallingAgent(today=date(2026, 6, 6))

    call = agent.plan(
        "Could you add Bible study tomorrow at 10:30 in the morning "
        "for half an hour?"
    )[0]

    assert call.name == ADD_CALENDAR_BLOCK_ACTION
    assert call.arguments == {
        "title": "Bible study",
        "start_time": "2026-06-07T10:30:00",
        "end_time": "2026-06-07T11:00:00",
    }


def test_calendar_block_accepts_written_minute_duration():
    agent = NlpToolCallingAgent(today=date(2026, 6, 6))

    call = agent.plan("Please book office hours Friday at 4 PM for forty minutes")[0]

    assert call.name == ADD_CALENDAR_BLOCK_ACTION
    assert call.arguments == {
        "title": "office hours",
        "start_time": "2026-06-12T16:00:00",
        "end_time": "2026-06-12T16:40:00",
    }


def test_calendar_lookup_with_between_times_does_not_create_block():
    agent = NlpToolCallingAgent(today=date(2026, 6, 6))

    call = agent.plan("What is on my calendar tomorrow between 2 PM and 3 PM?")[0]

    assert call.name == "get_calendar_events"


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
