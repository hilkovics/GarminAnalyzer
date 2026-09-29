"""/api/plan routes (phases 6–7): today's decision, week, season, goal, workout status and Garmin push."""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Query, Response

from training.api.deps import ConfigDep, SessionDep, TodayDep
from training.api.errors import INVALID, NOT_FOUND
from training.services import plan as service, plan_push
from training.services.dto import (
    DailyDecisionDTO,
    GoalDTO,
    GoalIn,
    PlannedWorkoutDTO,
    SeasonDTO,
    StatusIn,
    WeekPlanDTO,
)
from training.services.dto_plan import PushResultDTO

router = APIRouter(prefix="/plan", tags=["plan"])


@router.get(
    "/today",
    response_model=DailyDecisionDTO,
    responses=INVALID,
    summary="Today's planned workout; decided on the first call (redecided by the sync if made before it)",
)
def get_plan_today(session: SessionDep, today: TodayDep) -> DailyDecisionDTO:
    return service.get_today(session, today)


@router.post(
    "/today/regenerate",
    response_model=DailyDecisionDTO,
    responses=INVALID,
    summary="Decide today again, optionally for another sport (run | bike); a done workout stays",
)
def regenerate_today(session: SessionDep, today: TodayDep, sport: str | None = None) -> DailyDecisionDTO:
    return service.regenerate(session, today, sport)


@router.post(
    "/today/push",
    response_model=list[PushResultDTO],
    responses=INVALID,
    summary="Push today's planned workout(s) to Garmin Connect; a re-push updates, never duplicates",
)
def push_today(
    session: SessionDep, today: TodayDep, settings: ConfigDep, dry_run: bool = False
) -> list[PushResultDTO]:
    return plan_push.push_day(session, today, settings=settings, dry_run=dry_run)


@router.get(
    "/week",
    response_model=WeekPlanDTO,
    responses=INVALID,
    summary="The ISO week containing `date` (default today): targets, planned vs done per day",
)
def get_plan_week(
    session: SessionDep, today: TodayDep, day: Annotated[dt.date | None, Query(alias="date")] = None
) -> WeekPlanDTO:
    return service.get_week(session, day or today, today=today)


@router.get(
    "/season",
    response_model=SeasonDTO,
    summary="Season plan: this week and the projected weeks up to the race (phases, targets)",
)
def get_plan_season(session: SessionDep, today: TodayDep) -> SeasonDTO:
    return service.get_season(session, today)


@router.get("/goal", response_model=GoalDTO | None, summary="The active goal, or null")
def get_plan_goal(session: SessionDep, today: TodayDep) -> GoalDTO | None:
    return service.get_goal(session, today)


@router.put(
    "/goal",
    response_model=GoalDTO,
    responses=INVALID,
    summary="Set the goal race (replaces the active goal)",
)
def put_plan_goal(body: GoalIn, session: SessionDep, today: TodayDep) -> GoalDTO:
    return service.set_goal(session, body, today=today)


@router.delete(
    "/goal", status_code=204, summary="Clear the goal (the season falls back to the no-goal cycle)"
)
def delete_plan_goal(session: SessionDep) -> Response:
    service.clear_goal(session)
    return Response(status_code=204)


@router.get(
    "/{planned_id}",
    response_model=PlannedWorkoutDTO,
    responses={**NOT_FOUND, **INVALID},
    summary="One planned workout with its steps",
)
def get_planned(planned_id: int, session: SessionDep, today: TodayDep) -> PlannedWorkoutDTO:
    return service.get_planned(session, planned_id, today=today)


@router.post(
    "/{planned_id}/status",
    response_model=PlannedWorkoutDTO,
    responses={**NOT_FOUND, **INVALID},
    summary="Mark a planned workout done, skipped, or back to planned",
)
def post_plan_status(
    planned_id: int, body: StatusIn, session: SessionDep, today: TodayDep
) -> PlannedWorkoutDTO:
    return service.set_status(session, planned_id, body.status, today=today)


@router.post(
    "/{planned_id}/push",
    response_model=PushResultDTO,
    responses={**NOT_FOUND, **INVALID},
    summary="Push a planned workout to Garmin Connect and schedule it; dry_run returns the payload only",
)
def push_plan(
    planned_id: int, session: SessionDep, settings: ConfigDep, dry_run: bool = False
) -> PushResultDTO:
    return plan_push.push_planned(session, planned_id, settings=settings, dry_run=dry_run)
