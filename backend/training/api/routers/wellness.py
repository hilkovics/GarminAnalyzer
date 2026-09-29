"""/api/wellness routes (phase 5): daily wellness with baselines, readiness, sleep ↔ performance findings."""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Query

from training.api.deps import SessionDep, TodayDep
from training.api.errors import INVALID
from training.services import sleep as service
from training.services.dto import CorrelationsDTO, ReadinessDTO, WellnessDTO

router = APIRouter(prefix="/wellness", tags=["wellness"])


@router.get(
    "/daily",
    response_model=WellnessDTO,
    responses=INVALID,
    summary="Daily wellness rows with 28-day baselines, sleep debt and readiness",
)
def get_wellness(
    session: SessionDep,
    date_from: Annotated[dt.date | None, Query(alias="from")] = None,
    date_to: Annotated[dt.date | None, Query(alias="to")] = None,
) -> WellnessDTO:
    return service.get_wellness(session, date_from=date_from, date_to=date_to)


@router.get(
    "/readiness/today",
    response_model=ReadinessDTO,
    summary="Readiness of today with the component breakdown",
)
def get_readiness_today(session: SessionDep, today: TodayDep) -> ReadinessDTO:
    return service.get_readiness(session, today)


@router.get(
    "/readiness/{day}",
    response_model=ReadinessDTO,
    responses=INVALID,
    summary="Readiness of one day with the component breakdown",
)
def get_readiness(session: SessionDep, day: dt.date) -> ReadinessDTO:
    return service.get_readiness(session, day)


@router.get(
    "/correlations",
    response_model=CorrelationsDTO,
    responses=INVALID,
    summary="Sleep ↔ performance findings (n ≥ 30) sorted by |ρ|, plus pairs with insufficient data",
)
def get_correlations(session: SessionDep, sport: str | None = None) -> CorrelationsDTO:
    return service.get_correlations(session, sport=sport)
