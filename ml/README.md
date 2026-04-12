# Syntra — ML Module

Standalone machine learning components for the Syntra AI calendar assistant.
This folder is intentionally decoupled from the backend so models can be trained,
evaluated, and versioned independently.

## Models

| Model | Folder | Purpose |
|---|---|---|
| Task Duration Estimator | `models/task_estimator/` | Predict how long a task will take based on type, course, and history |
| Schedule Optimizer | `models/schedule_optimizer/` | Rank and place flexible blocks around fixed events |
| Intent Parser | `models/intent_parser/` | Classify natural language chat requests into schedule actions |

## Quickstart

```bash
cd ml
pip install -r requirements.txt
python scripts/train_task_estimator.py
```
