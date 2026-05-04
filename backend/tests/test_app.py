from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_openapi_available():
    r = client.get("/openapi.json")
    assert r.status_code == 200
    assert "openapi" in r.json()


def test_auth_health():
    r = client.get("/api/v1/auth/health")
    assert r.status_code == 200
    assert r.json().get("status") == "ok"


def test_tasks_list_empty():
    r = client.get("/api/v1/tasks/")
    assert r.status_code == 200
    assert r.json() == {"tasks": []}


def test_canvas_assignments_without_token_returns_503(monkeypatch):
    import app.core.config.settings as settings_mod

    monkeypatch.setattr(settings_mod.settings, "canvas_api_token", "")
    r = client.get("/api/v1/canvas/assignments")
    assert r.status_code == 503
    assert "CANVAS_API_TOKEN" in r.json().get("detail", "")


def test_chat_message():
    r = client.post(
        "/api/v1/chat/message",
        json={"message": "What is due this week?", "user_id": "test-user"},
    )
    assert r.status_code == 200
    assert "reply" in r.json()
    assert len(r.json()["reply"]) > 0


def test_schedule_suggest_empty_tasks():
    r = client.post(
        "/api/v1/schedule/suggest",
        json={"tasks": [], "fixed_events": [], "look_ahead_days": 7},
    )
    assert r.status_code == 200
    assert r.json() == {"blocks": []}


def test_schedule_suggest_returns_blocks():
    r = client.post(
        "/api/v1/schedule/suggest",
        json={
            "tasks": [
                {
                    "id": "t1",
                    "title": "Study",
                    "due_date": "2035-06-01T23:59:00",
                    "estimated_minutes": 45,
                }
            ],
            "fixed_events": [],
            "look_ahead_days": 14,
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert "blocks" in data
    assert len(data["blocks"]) >= 1
    b0 = data["blocks"][0]
    assert b0["task_id"] == "t1"
    assert "start_time" in b0 and "end_time" in b0
