"""Collaborative scheduling polls with privacy-safe availability sharing."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.collaboration_service import collaboration_service


router = APIRouter()


class BusyIntervalIn(BaseModel):
    start: datetime
    end: datetime
    flexibility: str = "fixed"


class ParticipantIn(BaseModel):
    id: str
    display_name: str = ""
    email: str = ""
    timezone_offset_minutes: int = Field(default=0, ge=-840, le=840)
    preferred_periods: list[str] = Field(default_factory=list)
    busy: list[BusyIntervalIn] = Field(default_factory=list)


class CreatePollIn(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    organizer_id: str = Field(min_length=1)
    duration_minutes: int = Field(ge=15, le=480)
    window_start: datetime
    window_end: datetime
    participants: list[ParticipantIn] = Field(min_length=1)
    description: str = Field(default="", max_length=2000)
    location: str = Field(default="", max_length=240)
    max_options: int = Field(default=5, ge=1, le=10)


class VoteIn(BaseModel):
    participant_id: str = Field(min_length=1)
    option_id: str = Field(min_length=1)
    response: str


class AvailabilityIn(BaseModel):
    participant_id: str = Field(min_length=1)
    timezone_offset_minutes: int = Field(default=0, ge=-840, le=840)
    preferred_periods: list[str] = Field(default_factory=list)
    busy: list[BusyIntervalIn] = Field(default_factory=list)


class ConfirmPollIn(BaseModel):
    organizer_id: str = Field(min_length=1)
    option_id: str = Field(min_length=1)


class CancelPollIn(BaseModel):
    organizer_id: str = Field(min_length=1)


def _detail(exc: Exception) -> HTTPException:
    if isinstance(exc, KeyError):
        return HTTPException(status_code=404, detail=str(exc.args[0]))
    if isinstance(exc, PermissionError):
        return HTTPException(status_code=403, detail=str(exc))
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/health")
async def collab_health() -> dict:
    return {"status": "ok", "privacy": "busy-only"}


@router.post("/polls")
async def create_poll(body: CreatePollIn) -> dict:
    """Create a poll using busy intervals only; event titles never leave clients."""

    try:
        return collaboration_service.create_poll(
            title=body.title,
            organizer_id=body.organizer_id,
            duration_minutes=body.duration_minutes,
            window_start=body.window_start,
            window_end=body.window_end,
            participants=[
                {
                    **participant.model_dump(exclude={"busy"}),
                    "busy": [interval.model_dump() for interval in participant.busy],
                }
                for participant in body.participants
            ],
            description=body.description,
            location=body.location,
            max_options=body.max_options,
        )
    except (KeyError, PermissionError, ValueError) as exc:
        raise _detail(exc) from exc


@router.get("/polls")
async def list_polls(
    user_id: str = Query(min_length=1),
    email: str = Query(default=""),
) -> dict:
    return {"polls": collaboration_service.list_polls(user_id, email)}


@router.get("/polls/{poll_id}")
async def get_poll(poll_id: str, user_id: str = Query(min_length=1)) -> dict:
    try:
        return collaboration_service.get_poll(poll_id, user_id)
    except (KeyError, PermissionError, ValueError) as exc:
        raise _detail(exc) from exc


@router.post("/polls/{poll_id}/votes")
async def vote_on_poll(poll_id: str, body: VoteIn) -> dict:
    try:
        return collaboration_service.vote(
            poll_id,
            participant_id=body.participant_id,
            option_id=body.option_id,
            response=body.response,
        )
    except (KeyError, PermissionError, ValueError) as exc:
        raise _detail(exc) from exc


@router.post("/polls/{poll_id}/availability")
async def update_availability(poll_id: str, body: AvailabilityIn) -> dict:
    """Replace one participant's private busy intervals and rerank poll options."""

    try:
        return collaboration_service.update_availability(
            poll_id,
            participant_id=body.participant_id,
            timezone_offset_minutes=body.timezone_offset_minutes,
            preferred_periods=body.preferred_periods,
            busy=[interval.model_dump() for interval in body.busy],
        )
    except (KeyError, PermissionError, ValueError) as exc:
        raise _detail(exc) from exc


@router.post("/polls/{poll_id}/confirm")
async def confirm_poll(poll_id: str, body: ConfirmPollIn) -> dict:
    try:
        return collaboration_service.confirm(
            poll_id,
            organizer_id=body.organizer_id,
            option_id=body.option_id,
        )
    except (KeyError, PermissionError, ValueError) as exc:
        raise _detail(exc) from exc


@router.post("/polls/{poll_id}/cancel")
async def cancel_poll(poll_id: str, body: CancelPollIn) -> dict:
    try:
        return collaboration_service.cancel(
            poll_id,
            organizer_id=body.organizer_id,
        )
    except (KeyError, PermissionError, ValueError) as exc:
        raise _detail(exc) from exc
