"""/api/wellness routes (phase 5): daily wellness with baselines, readiness, sleep ↔ performance findings."""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Query

from training.api.deps import SessionDep, TodayDep
from training.api.errors import INVALID
from training.services import health, sleep as service
from training.services.dto import (
    CorrelationsDTO,
    HealthOverviewDTO,
    HealthRelationshipsDTO,
    HealthSeriesDTO,
    ReadinessDTO,
    WellnessDTO,
)

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


@router.get(
    "/health",
    response_model=HealthOverviewDTO,
    summary="Health metrics (§12): latest, 7/28-day means, personal normal, 28-day change, monthly means",
)
def get_health(session: SessionDep, today: TodayDep) -> HealthOverviewDTO:
    return health.get_overview(session, today)


@router.get(
    "/health/series",
    response_model=list[HealthSeriesDTO],
    responses=INVALID,
    summary="Daily series of 1–4 health metrics with the 7-day mean and the normal band (§12.2)",
)
def get_health_series(
    session: SessionDep,
    today: TodayDep,
    metrics: Annotated[str, Query(description="comma-separated metric keys")],
    days: int = 180,
) -> list[HealthSeriesDTO]:
    return health.get_series(session, [m for m in metrics.split(",") if m], days=days, today=today)


@router.get(
    "/health/relationships",
    response_model=HealthRelationshipsDTO,
    summary="Relationships between deviations of health metrics (§12.3), findings first",
)
def get_health_relationships(session: SessionDep, today: TodayDep) -> HealthRelationshipsDTO:
    return health.get_relationships(session, today)
