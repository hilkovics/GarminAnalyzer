"""Settings: athlete, historical thresholds, zone preview."""

from fastapi import APIRouter

from training.api.deps import SessionDep, TodayDep
from training.api.errors import INVALID
from training.services import settings as service
from training.services.dto import AthleteDTO, AthleteIn, SettingsDTO, ThresholdDTO, ThresholdIn

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsDTO, summary="Athlete, threshold history, today's zone bounds")
def get_settings(session: SessionDep, today: TodayDep) -> SettingsDTO:
    return service.get_settings(session, today=today)


@router.put(
    "/thresholds",
    response_model=ThresholdDTO,
    responses=INVALID,
    summary="Add or replace a threshold from a date; recomputes only activities from that date on",
)
def put_threshold(body: ThresholdIn, session: SessionDep, today: TodayDep) -> ThresholdDTO:
    return service.add_threshold(session, body, today=today)


@router.put(
    "/athlete",
    response_model=AthleteDTO,
    responses=INVALID,
    summary="Update athlete fields (null = unchanged); TRIMP inputs recompute all metrics",
)
def put_athlete(body: AthleteIn, session: SessionDep, today: TodayDep) -> AthleteDTO:
    return service.update_athlete(session, body, today=today)
