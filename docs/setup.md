# Local Development Setup

## Prerequisites
- Flutter 3.x
- Python 3.11+
- PostgreSQL 15+
- Redis 7+

## 1. Backend

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in tokens
uvicorn app.main:app --reload
```

## 2. Flutter App

```bash
cd app
flutter pub get
flutter run
```

## 3. ML (optional, for training)

```bash
cd ml
pip install -r requirements.txt
jupyter notebook
```
