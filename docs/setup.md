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

### iOS: `SdkRoot` / `native_assets` errors

If you see **Target native_assets required define SdkRoot but it was not provided** on **hot reload**, that comes from Flutter’s `ResidentRunner` not passing `SdkRoot` into the native-assets build (see [flutter/flutter#180603](https://github.com/flutter/flutter/issues/180603)). Setting `SDKROOT` in the shell alone does **not** fix it.

**Fix (one time per machine, re-run after `flutter upgrade` if it comes back):**

```bash
cd /path/to/synctraCapstone
python3 tool/patch_flutter_resident_sdkroot.py apply
```

Then run `flutter doctor` or `flutter run` once so the Flutter tool snapshot rebuilds.

To undo: `python3 tool/patch_flutter_resident_sdkroot.py restore`

Optional: `cd app && bash scripts/run_ios.sh` or the **synctra (iOS)** launch config in `.vscode/launch.json` still sets Xcode-related env for other tooling.

## 3. ML (optional, for training)

```bash
cd ml
pip install -r requirements.txt
jupyter notebook
```
