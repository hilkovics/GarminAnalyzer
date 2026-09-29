"""Activities: list, detail, downsampled streams, subjective form."""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Query

from training.api.deps import SessionDep
from training.api.errors import INVALID, NOT_FOUND
from training.services import activities as service
from training.services.dto import (
    ActivityDetailDTO,
    ActivityListDTO,
    StreamsDTO,
    SubjectiveDTO,
    SubjectiveIn,
)

router = APIRouter(prefix="/activities", tags=["activities"])


@router.get("", response_model=ActivityListDTO, responses=INVALID, summary="List activities, newest first")
def list_activities(
    session: SessionDep,
    date_from: Annotated[dt.date | None, Query(alias="from", description="first local date")] = None,
    date_to: Annotated[dt.date | None, Query(alias="to", description="last local date")] = None,
    sport: Annotated[str | None, Query(description="run | bike | other")] = None,
    page: int = 1,
    page_size: Annotated[int, Query(description=f"1–{service.MAX_PAGE_SIZE}")] = 50,
) -> ActivityListDTO:
    return service.list_activities(
        session, date_from=date_from, date_to=date_to, sport=sport, page=page, page_size=page_size
    )


@router.get(
    "/{activity_id}",
    response_model=ActivityDetailDTO,
    responses={**NOT_FOUND, **INVALID},
    summary="Activity detail: metrics, laps, zones, subjective",
)
def get_activity(activity_id: int, session: SessionDep) -> ActivityDetailDTO:
    return service.get_activity(session, activity_id)


@router.get(
    "/{activity_id}/streams",
    response_model=StreamsDTO,
    responses={**NOT_FOUND, **INVALID},
    summary="LTTB-downsampled 1 Hz streams",
)
def get_streams(
    activity_id: int,
    session: SessionDep,
    fields: Annotated[
        str | None,
        Query(description=f"comma-separated: {', '.join(service.STREAM_FIELDS)} (default hr,speed,alt)"),
    ] = None,
    points: Annotated[int, Query(description=f"{service.MIN_POINTS}–{service.MAX_POINTS}")] = 1500,
) -> StreamsDTO:
    names = [f.strip() for f in fields.split(",") if f.strip()] if fields else None
    return service.get_streams(session, activity_id, names, points)


@router.post(
    "/{activity_id}/subjective",
    response_model=SubjectiveDTO,
    responses={**NOT_FOUND, **INVALID},
    summary="Save RPE / feel / soreness / notes (upsert, one row per activity)",
)
def save_subjective(activity_id: int, body: SubjectiveIn, session: SessionDep) -> SubjectiveDTO:
    return service.save_subjective(session, activity_id, body)
