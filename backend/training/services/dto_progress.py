"""Phase-4 progress DTOs (EF, curves, best efforts, predictions, threshold proposals – METRICS §5–§7);
re-exported by `services.dto`."""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field

# --- progress (phase 4, METRICS §5–§7) ---------------------------------------------------------------------


class SeriesPointDTO(BaseModel):
    activity_id: int
    local_date: dt.date
    value: float | None = Field(
        description="metric value of that activity (EF: m/min per bpm; pace metric: m/s)"
    )
    steady_state: bool | None


class TrendPointDTO(BaseModel):
    date: dt.date
    value: float | None = Field(description="28-day rolling median (METRICS §5.2)")


class SeriesDTO(BaseModel):
    """GET /progress/ef (EF / decoupling / pace_at_ref_hr_day per activity + trend)."""

    metric: str = Field(description='"ef" | "decoupling_pct" | "pace_at_ref_hr_day"')
    sport: str
    unit: str = Field(description='"m/min/bpm" | "%" | "m/s"')
    points: list[SeriesPointDTO] = Field(
        description="date ascending; EF/decoupling only for steady-state runs"
    )
    trend: list[TrendPointDTO] = Field(description="daily 28-day median over steady-state activities")
    caveat: str | None = Field(description="e.g. bike EF: terrain/wind dependent – trend only (§5.4)")


class CurveBinDTO(BaseModel):
    hr_bin: int = Field(description="lower edge of the 5 bpm bin")
    gap_speed: float = Field(description="median GAP speed in the bin, m/s")
    count: int


class CurveDTO(BaseModel):
    """GET /progress/speed-hr-curve – one month-end snapshot (§6.1)."""

    month: str = Field(description='"YYYY-MM"')
    sport: str
    bins: list[CurveBinDTO]
    ref_hr: float | None = Field(description="0.80 · LTHR valid at the window end, bpm")
    pace_at_ref_hr: float | None = Field(description="m/s")


class BestEffortDTO(BaseModel):
    kind: str = Field(description='"gap_speed" | "speed" | "hr"')
    window_s: int
    value: float = Field(description="m/s or bpm")
    local_date: dt.date
    activity_id: int
    distance_m: float | None


class BestEffortsDTO(BaseModel):
    """GET /progress/best-efforts?sport&range=90d|all (§6.2)."""

    sport: str
    range: str = Field(description='"90d" | "all"')
    efforts: list[BestEffortDTO] = Field(description="best per (kind, window_s)")


class ReferenceDTO(BaseModel):
    distance_m: float
    time_s: float
    local_date: dt.date
    source: str = Field(description='"race" | "effort"')
    vdot: float


class PredictionDTO(BaseModel):
    name: str = Field(description='"5k" | "10k" | "half" | "marathon"')
    distance_m: float
    riegel_s: float
    daniels_s: float
    extrapolated: bool = Field(description="reference distance < 1/4 of the target")


class PredictionsDTO(BaseModel):
    """GET /progress/predictions (§7)."""

    reference: ReferenceDTO | None
    stale: bool = Field(description="reference older than 60 days")
    predictions: list[PredictionDTO]


class ProposalDTO(BaseModel):
    """GET /progress/threshold-proposals (§6.3) – never auto-applied."""

    sport: str
    field: str = Field(description='"threshold_speed" (m/s) | "lthr" (bpm)')
    current: float | None
    estimate: float
    change: float | None = Field(
        description="relative (speed) or bpm (lthr) difference; null without current"
    )
    propose: bool
    basis: str
    garmin_lthr: float | None = Field(description="Garmin's own lactate-threshold HR, bpm (if available)")
    garmin_lt_speed: float | None = Field(description="Garmin's lactate-threshold speed, m/s (if available)")
    garmin_vo2max: float | None


class ProposalApplyIn(BaseModel):
    """POST /progress/threshold-proposals/apply body: the proposal to store as a threshold from today."""

    sport: Literal["run", "bike"]
    field: Literal["threshold_speed", "lthr"]


class ProposalGapDTO(BaseModel):
    """GET /progress/threshold-proposals/missing – why an estimate is missing (not part of §6.3)."""

    sport: str = Field(description='"run" | "bike"')
    field: str = Field(description='"threshold_speed" | "lthr"')
    reason: str = Field(description="why no estimate exists, e.g. no ride with 30 min of HR without a pause")
