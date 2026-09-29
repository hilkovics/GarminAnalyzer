"""Fitness: PMC series, weekly aggregates, dashboard."""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Query

from training.api.deps import SessionDep, TodayDep
from training.api.errors import INVALID
from training.services import fitness as service
from training.services.dto import DashboardDTO, PmcDTO, WeeklyDTO

router = APIRouter(prefix="/fitness", tags=["fitness"])


@router.get(
    "/pmc",
    response_model=PmcDTO,
    responses=INVALID,
    summary="Daily CTL/ATL/TSB/ACWR/monotony/ramp series with flags",
)
def get_pmc(
    session: SessionDep,
    date_from: Annotated[dt.date | None, Query(alias="from")] = None,
    date_to: Annotated[dt.date | None, Query(alias="to")] = None,
) -> PmcDTO:
    return service.get_pmc(session, date_from=date_from, date_to=date_to)


@router.get(
    "/weekly",
    response_model=list[WeeklyDTO],
    responses=INVALID,
    summary="ISO-week volume, zone time and polarization per sport",
)
def get_weekly(session: SessionDep, today: TodayDep, weeks: int = 12) -> list[WeeklyDTO]:
    return service.get_weekly(session, weeks=weeks, today=today)


@router.get(
    "/dashboard", response_model=DashboardDTO, summary="This week vs the last 4, PMC mini, sync health"
)
def get_dashboard(session: SessionDep, today: TodayDep) -> DashboardDTO:
    return service.get_dashboard(session, today=today)
