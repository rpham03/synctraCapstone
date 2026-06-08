"""Privacy-safe collaborative scheduling polls and deterministic time ranking."""

from __future__ import annotations

import threading
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any


PRODUCTIVITY_PERIODS = {
    "morning": (6, 12),
    "afternoon": (12, 17),
    "evening": (17, 21),
    "night": (21, 24),
}
VOTE_VALUES = {"available", "preferred", "unavailable"}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _utc(value).isoformat()


def _overlaps(start: datetime, end: datetime, busy: dict[str, Any]) -> bool:
    busy_start = _utc(busy["start"])
    busy_end = _utc(busy["end"])
    return start < busy_end and end > busy_start


def _normalize_busy_intervals(busy: list[dict[str, Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for interval in busy:
        start = _utc(interval["start"])
        end = _utc(interval["end"])
        if end <= start:
            raise ValueError("Busy interval end must be after start")
        normalized.append(
            {
                "start": start,
                "end": end,
                "flexibility": str(interval.get("flexibility") or "fixed"),
            }
        )
    return sorted(
        normalized,
        key=lambda interval: (interval["start"], interval["end"]),
    )


def _option_times(options: list[dict[str, Any]]) -> list[tuple[datetime, datetime]]:
    return [
        (_utc(option["start_time"]), _utc(option["end_time"])) for option in options
    ]


def _local_time(value: datetime, offset_minutes: int) -> datetime:
    return _utc(value) + timedelta(minutes=offset_minutes)


def _matches_preference(
    start: datetime,
    end: datetime,
    participant: dict[str, Any],
) -> bool:
    periods = participant.get("preferred_periods") or []
    if not periods:
        return False
    offset = int(participant.get("timezone_offset_minutes") or 0)
    local_start = _local_time(start, offset)
    local_end = _local_time(end, offset)
    if local_start.date() != local_end.date():
        return False
    start_minutes = local_start.hour * 60 + local_start.minute
    end_minutes = local_end.hour * 60 + local_end.minute
    for period in periods:
        bounds = PRODUCTIVITY_PERIODS.get(str(period).lower())
        if not bounds:
            continue
        lower = bounds[0] * 60
        upper = bounds[1] * 60
        if start_minutes >= lower and end_minutes <= upper:
            return True
    return False


def _within_reasonable_hours(
    start: datetime,
    end: datetime,
    participant: dict[str, Any],
) -> bool:
    offset = int(participant.get("timezone_offset_minutes") or 0)
    local_start = _local_time(start, offset)
    local_end = _local_time(end, offset)
    if local_start.date() != local_end.date():
        return False
    return (
        local_start.hour * 60 + local_start.minute >= 8 * 60
        and local_end.hour * 60 + local_end.minute <= 22 * 60
    )


def _public_participant(participant: dict[str, Any]) -> dict[str, Any]:
    """Never expose participant busy intervals or calendar event details."""

    return {
        "id": participant["id"],
        "display_name": participant["display_name"],
        "email": participant.get("email", ""),
        "timezone_offset_minutes": participant.get("timezone_offset_minutes", 0),
        "preferred_periods": list(participant.get("preferred_periods") or []),
        "response_status": participant.get("response_status", "invited"),
    }


class CollaborationService:
    """Process-local poll repository used by the current backend/Colab MVP."""

    def __init__(self) -> None:
        self._polls: dict[str, dict[str, Any]] = {}
        self._lock = threading.RLock()

    def clear(self) -> None:
        with self._lock:
            self._polls.clear()

    def create_poll(
        self,
        *,
        title: str,
        organizer_id: str,
        duration_minutes: int,
        window_start: datetime,
        window_end: datetime,
        participants: list[dict[str, Any]],
        description: str = "",
        location: str = "",
        max_options: int = 5,
    ) -> dict[str, Any]:
        start = _utc(window_start)
        end = _utc(window_end)
        if end <= start:
            raise ValueError("window_end must be after window_start")
        if duration_minutes < 15 or duration_minutes > 480:
            raise ValueError("duration_minutes must be between 15 and 480")

        normalized: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw in participants:
            participant_id = str(raw.get("id") or "").strip()
            if not participant_id or participant_id in seen:
                continue
            seen.add(participant_id)
            normalized.append(
                {
                    "id": participant_id,
                    "display_name": str(
                        raw.get("display_name") or raw.get("email") or participant_id
                    ).strip(),
                    "email": str(raw.get("email") or "").strip(),
                    "timezone_offset_minutes": int(
                        raw.get("timezone_offset_minutes") or 0
                    ),
                    "preferred_periods": [
                        str(value).lower()
                        for value in raw.get("preferred_periods") or []
                        if str(value).lower() in PRODUCTIVITY_PERIODS
                    ],
                    # Busy intervals are private and never returned by public methods.
                    "busy": _normalize_busy_intervals(list(raw.get("busy") or [])),
                    "response_status": (
                        "accepted" if participant_id == organizer_id else "invited"
                    ),
                }
            )
        if organizer_id not in seen:
            normalized.insert(
                0,
                {
                    "id": organizer_id,
                    "display_name": "Organizer",
                    "email": "",
                    "timezone_offset_minutes": 0,
                    "preferred_periods": [],
                    "busy": [],
                    "response_status": "accepted",
                },
            )
        if len(normalized) < 2:
            raise ValueError("At least two participants are required")

        poll_id = str(uuid.uuid4())
        poll = {
            "id": poll_id,
            "title": title.strip() or "Group event",
            "description": description.strip(),
            "location": location.strip(),
            "organizer_id": organizer_id,
            "duration_minutes": duration_minutes,
            "window_start": start,
            "window_end": end,
            "max_options": max_options,
            "participants": normalized,
            "options": self._rank_options(
                poll_id=poll_id,
                participants=normalized,
                duration_minutes=duration_minutes,
                window_start=start,
                window_end=end,
                max_options=max_options,
            ),
            "votes": {},
            "status": "open",
            "confirmed_option_id": None,
            "created_at": datetime.now(timezone.utc),
            "activity": [
                {
                    "action": "poll_created",
                    "actor_id": organizer_id,
                    "created_at": datetime.now(timezone.utc),
                }
            ],
        }
        with self._lock:
            self._polls[poll_id] = poll
        return self._public_poll(poll)

    def list_polls(self, user_id: str, email: str = "") -> list[dict[str, Any]]:
        normalized_email = email.strip().lower()
        with self._lock:
            polls = [
                self._public_poll(poll)
                for poll in self._polls.values()
                if any(
                    p["id"] == user_id
                    or (
                        normalized_email
                        and str(p.get("email") or "").lower() == normalized_email
                    )
                    for p in poll["participants"]
                )
            ]
        return sorted(polls, key=lambda poll: poll["created_at"], reverse=True)

    def get_poll(self, poll_id: str, user_id: str) -> dict[str, Any]:
        with self._lock:
            poll = self._require_poll(poll_id)
            self._require_member(poll, user_id)
            return self._public_poll(poll)

    def vote(
        self,
        poll_id: str,
        *,
        participant_id: str,
        option_id: str,
        response: str,
    ) -> dict[str, Any]:
        normalized_response = response.lower().strip()
        if normalized_response not in VOTE_VALUES:
            raise ValueError("response must be available, preferred, or unavailable")
        with self._lock:
            poll = self._require_poll(poll_id)
            self._require_open(poll)
            self._require_member(poll, participant_id)
            self._require_option(poll, option_id)
            poll["votes"][f"{participant_id}:{option_id}"] = {
                "participant_id": participant_id,
                "option_id": option_id,
                "response": normalized_response,
                "created_at": datetime.now(timezone.utc),
            }
            for participant in poll["participants"]:
                if participant["id"] == participant_id:
                    participant["response_status"] = "responded"
                    break
            poll["activity"].append(
                {
                    "action": "vote_recorded",
                    "actor_id": participant_id,
                    "option_id": option_id,
                    "created_at": datetime.now(timezone.utc),
                }
            )
            return self._public_poll(poll)

    def update_availability(
        self,
        poll_id: str,
        *,
        participant_id: str,
        timezone_offset_minutes: int,
        preferred_periods: list[str],
        busy: list[dict[str, Any]],
    ) -> dict[str, Any]:
        with self._lock:
            poll = self._require_poll(poll_id)
            self._require_open(poll)
            participant = next(
                (
                    item
                    for item in poll["participants"]
                    if item["id"] == participant_id
                ),
                None,
            )
            if participant is None:
                raise PermissionError("Only poll participants can share availability")
            normalized_periods = [
                value.lower()
                for value in preferred_periods
                if value.lower() in PRODUCTIVITY_PERIODS
            ]
            normalized_busy = _normalize_busy_intervals(busy)
            changed = (
                participant["timezone_offset_minutes"] != timezone_offset_minutes
                or participant["preferred_periods"] != normalized_periods
                or participant["busy"] != normalized_busy
                or participant["response_status"] == "invited"
            )
            if not changed:
                return self._public_poll(poll)

            participant["timezone_offset_minutes"] = timezone_offset_minutes
            participant["preferred_periods"] = normalized_periods
            participant["busy"] = normalized_busy
            if participant["response_status"] == "invited":
                participant["response_status"] = "accepted"

            previous_option_times = _option_times(poll["options"])
            ranked_options = self._rank_options(
                poll_id=poll["id"],
                participants=poll["participants"],
                duration_minutes=poll["duration_minutes"],
                window_start=poll["window_start"],
                window_end=poll["window_end"],
                max_options=poll["max_options"],
            )
            poll["options"] = ranked_options
            if previous_option_times != _option_times(ranked_options):
                # Option IDs are rank-based, so votes cannot survive changed candidates.
                poll["votes"] = {}
                for item in poll["participants"]:
                    if item["response_status"] == "responded":
                        item["response_status"] = "accepted"
            poll["activity"].append(
                {
                    "action": "availability_refreshed",
                    "actor_id": participant_id,
                    "created_at": datetime.now(timezone.utc),
                }
            )
            return self._public_poll(poll)

    def confirm(
        self,
        poll_id: str,
        *,
        organizer_id: str,
        option_id: str,
    ) -> dict[str, Any]:
        with self._lock:
            poll = self._require_poll(poll_id)
            self._require_open(poll)
            if poll["organizer_id"] != organizer_id:
                raise PermissionError("Only the organizer can confirm this poll")
            option = self._require_option(poll, option_id)
            option_votes = [
                vote
                for vote in poll["votes"].values()
                if vote["option_id"] == option_id
            ]
            responded = {vote["participant_id"] for vote in option_votes}
            if any(
                participant["id"] not in responded
                for participant in poll["participants"]
            ):
                raise ValueError(
                    "Every participant must vote on this option before confirmation"
                )
            unavailable = [
                vote for vote in option_votes if vote["response"] == "unavailable"
            ]
            if unavailable:
                raise ValueError("This option has unavailable votes and cannot be confirmed")
            poll["status"] = "confirmed"
            poll["confirmed_option_id"] = option_id
            poll["activity"].append(
                {
                    "action": "poll_confirmed",
                    "actor_id": organizer_id,
                    "option_id": option_id,
                    "created_at": datetime.now(timezone.utc),
                }
            )
            result = self._public_poll(poll)
            result["calendar_events"] = [
                {
                    "id": f"collab-{poll_id}-{participant['id']}",
                    "participant_id": participant["id"],
                    "title": poll["title"],
                    "description": poll["description"],
                    "location": poll["location"],
                    "start_time": option["start_time"],
                    "end_time": option["end_time"],
                    "source": "collab",
                    "is_fixed": True,
                }
                for participant in poll["participants"]
            ]
            return result

    def cancel(self, poll_id: str, *, organizer_id: str) -> dict[str, Any]:
        with self._lock:
            poll = self._require_poll(poll_id)
            if poll["organizer_id"] != organizer_id:
                raise PermissionError("Only the organizer can cancel this poll")
            if poll["status"] == "confirmed":
                raise ValueError("Confirmed events must be cancelled from the calendar")
            poll["status"] = "cancelled"
            poll["activity"].append(
                {
                    "action": "poll_cancelled",
                    "actor_id": organizer_id,
                    "created_at": datetime.now(timezone.utc),
                }
            )
            return self._public_poll(poll)

    def _rank_options(
        self,
        *,
        poll_id: str,
        participants: list[dict[str, Any]],
        duration_minutes: int,
        window_start: datetime,
        window_end: datetime,
        max_options: int,
    ) -> list[dict[str, Any]]:
        duration = timedelta(minutes=duration_minutes)
        cursor = window_start.replace(second=0, microsecond=0)
        remainder = cursor.minute % 30
        if remainder:
            cursor += timedelta(minutes=30 - remainder)

        candidates: list[tuple[int, datetime, datetime, int]] = []
        while cursor + duration <= window_end:
            candidate_end = cursor + duration
            if all(
                _within_reasonable_hours(cursor, candidate_end, participant)
                and not any(
                    _overlaps(cursor, candidate_end, busy)
                    for busy in participant.get("busy") or []
                )
                for participant in participants
            ):
                preferred_matches = sum(
                    1
                    for participant in participants
                    if _matches_preference(cursor, candidate_end, participant)
                )
                # Preference matches dominate; earlier options break ties.
                score = preferred_matches * 100
                candidates.append((score, cursor, candidate_end, preferred_matches))
            cursor += timedelta(minutes=30)

        candidates.sort(key=lambda item: (-item[0], item[1]))
        options: list[dict[str, Any]] = []
        for index, (score, start, end, preferred_matches) in enumerate(
            candidates[: max(1, min(max_options, 10))],
            start=1,
        ):
            options.append(
                {
                    "id": f"{poll_id}-option-{index}",
                    "start_time": start,
                    "end_time": end,
                    "score": score,
                    "preferred_matches": preferred_matches,
                    "all_participants_available": True,
                }
            )
        return options

    def _public_poll(self, poll: dict[str, Any]) -> dict[str, Any]:
        result = {
            "id": poll["id"],
            "title": poll["title"],
            "description": poll["description"],
            "location": poll["location"],
            "organizer_id": poll["organizer_id"],
            "duration_minutes": poll["duration_minutes"],
            "window_start": _iso(poll["window_start"]),
            "window_end": _iso(poll["window_end"]),
            "participants": [
                _public_participant(participant) for participant in poll["participants"]
            ],
            "options": [
                {
                    **{
                        key: value
                        for key, value in option.items()
                        if key not in {"start_time", "end_time"}
                    },
                    "start_time": _iso(option["start_time"]),
                    "end_time": _iso(option["end_time"]),
                    "votes": self._vote_summary(poll, option["id"]),
                }
                for option in poll["options"]
            ],
            "status": poll["status"],
            "confirmed_option_id": poll["confirmed_option_id"],
            "created_at": _iso(poll["created_at"]),
            "activity": [
                {
                    **{
                        key: value
                        for key, value in item.items()
                        if key != "created_at"
                    },
                    "created_at": _iso(item["created_at"]),
                }
                for item in poll["activity"]
            ],
        }
        return deepcopy(result)

    def _vote_summary(self, poll: dict[str, Any], option_id: str) -> dict[str, int]:
        summary = {value: 0 for value in VOTE_VALUES}
        for vote in poll["votes"].values():
            if vote["option_id"] == option_id:
                summary[vote["response"]] += 1
        return summary

    def _require_poll(self, poll_id: str) -> dict[str, Any]:
        poll = self._polls.get(poll_id)
        if not poll:
            raise KeyError("Scheduling poll not found")
        return poll

    def _require_member(self, poll: dict[str, Any], user_id: str) -> None:
        if not any(participant["id"] == user_id for participant in poll["participants"]):
            raise PermissionError("Only poll participants can access this poll")

    def _require_open(self, poll: dict[str, Any]) -> None:
        if poll["status"] != "open":
            raise ValueError("This scheduling poll is no longer open")

    def _require_option(self, poll: dict[str, Any], option_id: str) -> dict[str, Any]:
        option = next(
            (option for option in poll["options"] if option["id"] == option_id),
            None,
        )
        if not option:
            raise KeyError("Scheduling option not found")
        return option


collaboration_service = CollaborationService()
