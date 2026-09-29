"""/api/progress routes (phase 4): EF series, speed–HR curves, best efforts, predictions, proposals."""

from fastapi import APIRouter

from training.api.deps import SessionDep, TodayDep
from training.api.errors import INVALID
from training.services import progress as service
from training.services.dto import BestEffortsDTO, CurveDTO, PredictionsDTO, ProposalDTO, SeriesDTO

router = APIRouter(prefix="/progress", tags=["progress"])


@router.get(
    "/ef",
    response_model=SeriesDTO,
    responses=INVALID,
    summary="EF / decoupling / pace at reference HR per activity with the 28-day median trend",
)
def get_ef_series(
    session: SessionDep, today: TodayDep, sport: str = "run", days: int = 180, metric: str = "ef"
) -> SeriesDTO:
    return service.get_ef_series(session, sport=sport, days=days, today=today, metric=metric)


@router.get(
    "/speed-hr-curve",
    response_model=list[CurveDTO],
    responses=INVALID,
    summary="Month-end speed-HR curve snapshots of the last N months, oldest first",
)
def get_speed_hr_curves(session: SessionDep, today: TodayDep, months: int = 6) -> list[CurveDTO]:
    return service.get_speed_hr_curves(session, months=months, today=today)


@router.get(
    "/best-efforts",
    response_model=BestEffortsDTO,
    responses=INVALID,
    summary="Best effort per (kind, window) over the last 90 days or all time",
)
def get_best_efforts(
    session: SessionDep, today: TodayDep, sport: str = "run", range: str = "90d"
) -> BestEffortsDTO:
    return service.get_best_efforts(session, sport=sport, range=range, today=today)


@router.get(
    "/predictions",
    response_model=PredictionsDTO,
    summary="Riegel and Daniels race predictions from the best recent reference",
)
def get_predictions(session: SessionDep, today: TodayDep) -> PredictionsDTO:
    return service.get_predictions(session, today=today)


@router.get(
    "/threshold-proposals",
    response_model=list[ProposalDTO],
    summary="LTHR / threshold-speed proposals (never applied automatically)",
)
def get_threshold_proposals(session: SessionDep, today: TodayDep) -> list[ProposalDTO]:
    return service.get_threshold_proposals(session, today=today)
