"""/api/reports routes (phase 7): the stored weekly AI report and its (explicit) generation."""

from fastapi import APIRouter

from training.api.deps import ConfigDep, SessionDep, TodayDep
from training.api.errors import INVALID, NOT_FOUND, UPSTREAM
from training.services import report as service
from training.services.dto import ReportDTO
from training.services.errors import NotFoundError

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get(
    "/latest",
    response_model=ReportDTO,
    responses=NOT_FOUND,
    summary="The newest stored weekly report (404 when there is none)",
)
def get_latest_report(settings: ConfigDep) -> ReportDTO:
    found = service.latest_report(settings)
    if found is None:
        raise NotFoundError("no weekly report has been generated yet")
    return found


@router.post(
    "/weekly",
    response_model=ReportDTO,
    responses={**INVALID, **UPSTREAM},
    summary="Generate and store this week's report (needs TRAINING_ANTHROPIC_API_KEY; 422 without it)",
)
def post_weekly_report(session: SessionDep, today: TodayDep, settings: ConfigDep) -> ReportDTO:
    return service.create_weekly_report(session, today, settings)
