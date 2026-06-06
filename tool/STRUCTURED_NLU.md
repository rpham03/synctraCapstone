# Syntra Structured NLU

Syntra uses a hybrid NLU pipeline:

1. An intent classifier chooses a tool.
2. A token-classification model extracts slots.
3. Deterministic rules normalize dates, times, and durations.
4. The backend verifies tool choice and required arguments before execution.
5. Missing or invalid slots produce a follow-up question.

## Canonical Data

Canonical examples use JSONL. Each line follows this shape:

```json
{
  "user_message": "Study for CSE 369 Thursday from 7 PM to 9 PM",
  "intent": "create_calendar_event",
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
```

Incomplete requests include known slots and list the missing required slots:

```json
{
  "user_message": "Add a calendar block tomorrow",
  "intent": "create_calendar_event",
  "tool": "add_calendar_block",
  "slots": {
    "date": "tomorrow"
  },
  "needs_followup": true,
  "missing_slots": ["title", "start_time", "end_time"],
  "followup_question": "What event name, start time, and end time should I use?"
}
```

`tool/syntra_nlu_training_data.jsonl` contains exactly 1,000 deterministic,
balanced examples shared by both models. Each model trains on 700 examples and
evaluates on the remaining 300 examples.

Regenerate the checked-in dataset after changing its templates:

```bash
python tool/generate_structured_nlu_dataset.py
```

## Training In Colab

The one-click trainer now trains both models:

```bash
python /content/syntra/tool/one_click_train_nlp_router_colab.py
```

The default training run uses:

```text
shared structured examples: 1000
training examples per model: 700
testing examples per model: 300
training examples per tool: 100
```

Both model directories include `training_meta.json` with the actual split
counts used by that run.

Output:

```text
/content/syntra_tool_router/             intent classifier
/content/syntra_tool_router/slot_model/  slot extractor
```

To train only the slot model:

```bash
python /content/syntra/tool/train_nlu_slot_model.py \
  --data /content/syntra/tool/syntra_nlu_training_data.jsonl \
  --output-dir /content/syntra_tool_router/slot_model
```

The NLP router server automatically loads `slot_model` when that directory is
present. `GET /health` reports `has_trained_model` and `has_slot_model`.

## Runtime Safety

Learned slots never directly bypass validation. Syntra still:

- asks for required missing slots;
- rejects an end time that is not after the start time;
- remembers pending clarification context per user;
- verifies the selected tool before execution;
- falls back to deterministic extraction when the slot model is unavailable.
