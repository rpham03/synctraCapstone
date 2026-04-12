# Syntra — AI Calendar Assistant

Syntra is an AI-powered calendar assistant that unifies Canvas assignments, class schedules, Google Calendar, and work shifts into one adaptive schedule. It separates fixed events from flexible tasks, estimates task durations, protects focus time, and lets users make changes through a natural language chat interface.

## Project Structure

```
syntraCapstone/
├── app/            # Flutter mobile/web application
├── backend/        # Python FastAPI backend & integrations
├── ml/             # Machine learning models (standalone)
├── docs/           # Design docs, diagrams, and API specs
└── .github/        # CI/CD workflows
```

## MVP Goals

1. Import events from Canvas and Google Calendar
2. Suggest study/work blocks based on due dates and estimated task length
3. Chat interface for natural language schedule adjustments

## Tech Stack

- **Frontend**: Flutter (iOS, Android, Web)
- **Backend**: Python + FastAPI
- **ML**: Python (scikit-learn / PyTorch)
- **Integrations**: Canvas LMS API, Google Calendar API
- **Database**: PostgreSQL + Redis (caching)

## Getting Started

See [docs/setup.md](docs/setup.md) for local development instructions.
