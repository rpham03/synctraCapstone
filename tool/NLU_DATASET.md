# Syntra NLU Dataset

`syntra_nlu_training_data.jsonl` is the canonical shared dataset for the intent
classifier and slot extractor. Regenerate it with:

```bash
python tool/generate_structured_nlu_dataset.py
```

## Evaluation Splits

The 5,000 rows have fixed split metadata:

- `train`: 3,500 rows used to fit both models.
- `development`: 500 rows used during training and model tuning.
- `unseen_template_test`: 500 rows from slot-normalized template families that
  occur in neither training nor development.
- `human_style_test`: 500 generated conversational/noisy proxy rows.

Development, unseen-template, and human-style suites are balanced to 29-30
examples per tool. Both realistic test suites cover every supported slot type.
Template families are interleaved before row selection so one large generated
product cannot crowd out the other wording families for a tool.

The human-style suite is not a real human-written benchmark. Before reporting
human accuracy, replace or extend it with untouched prompts collected from
people who did not see the generated templates.

## Training Mix

The training rows use this generated mix:

- 35% structured generated
- 25% conversational generated
- 15% paraphrase generated
- 10% noisy generated
- 10% clarification generated
- 5% hard-boundary generated

The training pool includes explicit hard-boundary wording for commonly confused
intents, including task-list versus live Canvas sync, calendar listing versus
event deletion, one-event versus whole-calendar classification, and
classification questions versus fixed/flexible overrides. Assignment-sync
examples always name a live source such as Canvas, LMS, or a course portal.

Every row records `source`, `difficulty`, `split`, and `template_family_id`.
`syntra_nlu_dataset_manifest.json` records split counts, label counts, source
mix, per-split slot coverage, per-tool template-family counts, and
template-family leakage checks.

## Reporting Results

Do not report one combined random-held-out accuracy. Report these separately:

1. Development metrics for model selection.
2. Unseen-template metrics for wording generalization.
3. Human-style proxy metrics for conversational/noisy robustness.
4. A separately collected untouched human benchmark when available.

Only the fourth result should be called human-written evaluation accuracy.
