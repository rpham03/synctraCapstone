from datetime import datetime

from fastapi.testclient import TestClient
import pytest

from app.main import app
from app.services.collaboration_service import collaboration_service


client = TestClient(app)


@pytest.fixture(autouse=True)
def clear_collaboration_repository():
    collaboration_service.clear()
    yield
    collaboration_service.clear()


def _poll_payload() -> dict:
    return {
        "title": "CSE 369 Project Meeting",
        "description": "Agree on project milestones",
        "organizer_id": "alex",
        "duration_minutes": 60,
        "window_start": "2026-06-08T08:00:00Z",
        "window_end": "2026-06-08T18:00:00Z",
        "participants": [
            {
                "id": "alex",
                "display_name": "Alex",
                "timezone_offset_minutes": 0,
                "preferred_periods": ["afternoon"],
                "busy": [
                    {
                        "start": "2026-06-08T08:00:00Z",
                        "end": "2026-06-08T10:00:00Z",
                    }
                ],
            },
            {
                "id": "jordan",
                "display_name": "Jordan",
                "timezone_offset_minutes": 0,
                "preferred_periods": ["afternoon"],
                "busy": [
                    {
                        "start": "2026-06-08T10:00:00Z",
                        "end": "2026-06-08T12:00:00Z",
                    }
                ],
            },
        ],
    }


def test_collab_health():
    response = client.get("/api/v1/collab/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "privacy": "busy-only"}


def test_create_poll_returns_ranked_privacy_safe_options():
    response = client.post("/api/v1/collab/polls", json=_poll_payload())

    assert response.status_code == 200
    poll = response.json()
    assert poll["status"] == "open"
    assert len(poll["participants"]) == 2
    assert len(poll["options"]) == 5
    assert poll["options"][0]["start_time"] == "2026-06-08T12:00:00+00:00"
    assert poll["options"][0]["preferred_matches"] == 2
    assert "busy" not in poll["participants"][0]
    assert "event title" not in response.text.lower()


def test_poll_vote_confirmation_and_access_control():
    poll = client.post("/api/v1/collab/polls", json=_poll_payload()).json()
    poll_id = poll["id"]
    option_id = poll["options"][0]["id"]

    forbidden = client.get(f"/api/v1/collab/polls/{poll_id}?user_id=outsider")
    assert forbidden.status_code == 403

    unavailable = client.post(
        f"/api/v1/collab/polls/{poll_id}/votes",
        json={
            "participant_id": "jordan",
            "option_id": option_id,
            "response": "unavailable",
        },
    )
    assert unavailable.status_code == 200
    assert unavailable.json()["options"][0]["votes"]["unavailable"] == 1

    organizer_vote = client.post(
        f"/api/v1/collab/polls/{poll_id}/votes",
        json={
            "participant_id": "alex",
            "option_id": option_id,
            "response": "available",
        },
    )
    assert organizer_vote.status_code == 200

    blocked = client.post(
        f"/api/v1/collab/polls/{poll_id}/confirm",
        json={"organizer_id": "alex", "option_id": option_id},
    )
    assert blocked.status_code == 400
    assert "unavailable votes" in blocked.json()["detail"]

    preferred = client.post(
        f"/api/v1/collab/polls/{poll_id}/votes",
        json={
            "participant_id": "jordan",
            "option_id": option_id,
            "response": "preferred",
        },
    )
    assert preferred.status_code == 200

    confirmed = client.post(
        f"/api/v1/collab/polls/{poll_id}/confirm",
        json={"organizer_id": "alex", "option_id": option_id},
    )
    assert confirmed.status_code == 200
    body = confirmed.json()
    assert body["status"] == "confirmed"
    assert len(body["calendar_events"]) == 2
    assert {event["participant_id"] for event in body["calendar_events"]} == {
        "alex",
        "jordan",
    }
    assert all(event["source"] == "collab" for event in body["calendar_events"])


def test_only_organizer_can_cancel_or_confirm():
    poll = client.post("/api/v1/collab/polls", json=_poll_payload()).json()
    poll_id = poll["id"]
    option_id = poll["options"][0]["id"]

    confirm = client.post(
        f"/api/v1/collab/polls/{poll_id}/confirm",
        json={"organizer_id": "jordan", "option_id": option_id},
    )
    cancel = client.post(
        f"/api/v1/collab/polls/{poll_id}/cancel",
        json={"organizer_id": "jordan"},
    )

    assert confirm.status_code == 403
    assert cancel.status_code == 403


def test_organizer_cannot_confirm_until_every_participant_votes():
    poll = client.post("/api/v1/collab/polls", json=_poll_payload()).json()

    response = client.post(
        f"/api/v1/collab/polls/{poll['id']}/confirm",
        json={"organizer_id": "alex", "option_id": poll["options"][0]["id"]},
    )

    assert response.status_code == 400
    assert "Every participant must vote" in response.json()["detail"]


def test_invited_participant_can_find_poll_by_email():
    payload = _poll_payload()
    payload["participants"][1]["id"] = "invite-token-jordan"
    payload["participants"][1]["email"] = "jordan@example.com"
    poll = client.post("/api/v1/collab/polls", json=payload).json()

    response = client.get(
        "/api/v1/collab/polls",
        params={"user_id": "different-auth-id", "email": "jordan@example.com"},
    )

    assert response.status_code == 200
    assert [item["id"] for item in response.json()["polls"]] == [poll["id"]]


def test_participant_availability_refresh_reranks_without_exposing_busy_details():
    poll = client.post("/api/v1/collab/polls", json=_poll_payload()).json()
    poll_id = poll["id"]

    refreshed = client.post(
        f"/api/v1/collab/polls/{poll_id}/availability",
        json={
            "participant_id": "jordan",
            "timezone_offset_minutes": 0,
            "preferred_periods": ["afternoon"],
            "busy": [
                {
                    "start": "2026-06-08T12:00:00Z",
                    "end": "2026-06-08T16:00:00Z",
                }
            ],
        },
    )

    assert refreshed.status_code == 200
    body = refreshed.json()
    assert body["options"][0]["start_time"] == "2026-06-08T16:00:00+00:00"
    assert "busy" not in body["participants"][1]
    busy_start = datetime.fromisoformat("2026-06-08T12:00:00+00:00")
    busy_end = datetime.fromisoformat("2026-06-08T16:00:00+00:00")
    for option in body["options"]:
        option_start = datetime.fromisoformat(option["start_time"])
        option_end = datetime.fromisoformat(option["end_time"])
        assert not (option_start < busy_end and option_end > busy_start)


def test_unchanged_availability_refresh_preserves_existing_votes():
    poll = client.post("/api/v1/collab/polls", json=_poll_payload()).json()
    poll_id = poll["id"]
    option_id = poll["options"][0]["id"]
    client.post(
        f"/api/v1/collab/polls/{poll_id}/votes",
        json={
            "participant_id": "jordan",
            "option_id": option_id,
            "response": "preferred",
        },
    )

    refreshed = client.post(
        f"/api/v1/collab/polls/{poll_id}/availability",
        json={
            "participant_id": "jordan",
            "timezone_offset_minutes": 0,
            "preferred_periods": ["afternoon"],
            "busy": [
                {
                    "start": "2026-06-08T10:00:00Z",
                    "end": "2026-06-08T12:00:00Z",
                }
            ],
        },
    )

    assert refreshed.status_code == 200
    assert refreshed.json()["options"][0]["votes"]["preferred"] == 1
    assert refreshed.json()["participants"][1]["response_status"] == "responded"


def test_invalid_busy_interval_is_rejected():
    poll = client.post("/api/v1/collab/polls", json=_poll_payload()).json()

    response = client.post(
        f"/api/v1/collab/polls/{poll['id']}/availability",
        json={
            "participant_id": "jordan",
            "busy": [
                {
                    "start": "2026-06-08T12:00:00Z",
                    "end": "2026-06-08T10:00:00Z",
                }
            ],
        },
    )

    assert response.status_code == 400
    assert "end must be after start" in response.json()["detail"]
