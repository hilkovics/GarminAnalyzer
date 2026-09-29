"""Sync and diagnostics."""

from fastapi import APIRouter

from training.api.deps import ConfigDep, SessionDep, TodayDep
from training.api.errors import UPSTREAM
from training.services import diagnostics, sync
from training.services.dto import DiagnosticsDTO, SyncResultDTO

router = APIRouter(tags=["sync"])


@router.get("/diagnostics", response_model=DiagnosticsDTO, summary="Sync state and the load sanity check")
def get_diagnostics(session: SessionDep) -> DiagnosticsDTO:
    return diagnostics.get_diagnostics(session)


@router.post(
    "/sync",
    response_model=SyncResultDTO,
    responses=UPSTREAM,
    summary="Run an incremental Garmin sync now (synchronous, local use only)",
)
def post_sync(session: SessionDep, today: TodayDep, settings: ConfigDep) -> SyncResultDTO:
    return sync.run_sync(session, settings=settings, today=today)
