"""Coach "Kondícia" block progress DTOs (METRICS §11.4); re-exported by `services.dto`.

Internal units: pace as speed m/s (higher = faster), EF m/min/bpm, times and durations in seconds.
"""

import datetime as dt

from pydantic import BaseModel, Field


class FitnessSnapshotDTO(BaseModel):
    """§11.4 fitness on `day` (runs only); every part is null without data."""

    day: dt.date
    pace_at_ref_hr: float | None = Field(description="m/s, 28-day median of pace at the reference HR (§6.1)")
    ef: float | None = Field(description="§5.2 EF trend, m/min/bpm")
    vdot: float | None = Field(description="§7 reference VDOT as of the day")
    t5k_s: float | None = Field(description="Daniels equivalent 5 km time")
    t10k_s: float | None = Field(description="Daniels equivalent 10 km time")
    reference_date: dt.date | None = Field(description="date of the §7 reference (stale when > 60 days old)")


class FitnessChangeDTO(BaseModel):
    """Week value − baseline: pace, EF, VDOT + = better; times − = better."""

    pace_at_ref_hr: float | None
    ef: float | None
    vdot: float | None
    t5k_s: float | None
    t10k_s: float | None


class BlockWeekDTO(BaseModel):
    monday: dt.date
    week_no: int
    target_s: float
    run_s: float = Field(description="non-commute running time done")
    items_done: int = Field(description="menu items done (0–3)")
    brake: str | None
    recovery: bool
    test: bool
    mean_readiness: float | None
    mean_sleep_s: float | None
    value: FitnessSnapshotDTO = Field(
        description="snapshot on the week's Sunday (today for the running week)"
    )
    change: FitnessChangeDTO | None = Field(description="value − baseline")


class CheckRunDTO(BaseModel):
    """A check run's result: the 30-min effort and its Daniels equivalents."""

    date: dt.date
    activity_id: int
    distance_m: float = Field(description="distance in the 30-min effort")
    avg_hr: float | None = Field(description="mean HR of the 30-min HR effort")
    vdot: float
    t5k_s: float
    t10k_s: float


class BlockSummaryDTO(BaseModel):
    final: bool = Field(description="week 12 is over (else: so far)")
    weeks: int
    items_done: int
    items_planned: int
    run_s: float
    target_s: float
    brake_weeks: int
    mean_readiness: float | None
    mean_sleep_s: float | None
    green_share: float | None = Field(description="share of days with readiness ≥ 70")
    change: FitnessChangeDTO | None = Field(description="last week value − baseline")


class BlockProgressDTO(BaseModel):
    """GET /plan/block – one 12-week block of the coach "Kondícia"."""

    start: dt.date
    end: dt.date
    block_weeks: int
    baseline: FitnessSnapshotDTO = Field(description="snapshot on the day before the block")
    weeks: list[BlockWeekDTO] = Field(description="weeks that have started, oldest first")
    check_runs: list[CheckRunDTO]
    summary: BlockSummaryDTO


class BlockRefDTO(BaseModel):
    start: dt.date
    end: dt.date
    current: bool
