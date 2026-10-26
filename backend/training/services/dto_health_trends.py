"""Health page DTOs (METRICS §12); re-exported by `services.dto`. Internal units (s, bpm, counts, points)."""

import datetime as dt

from pydantic import BaseModel, Field


class RecentChangeDTO(BaseModel):
    """Last 28 days vs the 28 before (§12.2)."""

    recent: float | None
    previous: float | None
    diff: float | None
    pct: float | None = Field(description="diff / previous")
    p: float | None = Field(description="Mann–Whitney U, two-sided")
    notable: bool = Field(description="p < 0.05")
    direction: str | None = Field(description='"better" | "worse" | null (no preferred direction)')


class MonthValueDTO(BaseModel):
    month: str = Field(description='"YYYY-MM"')
    value: float


class HealthMetricDTO(BaseModel):
    key: str
    label: str
    unit: str = Field(description='"s", "bpm", "min", … ("" for scores and counts)')
    better: str | None = Field(description='"up" | "down" | null')
    latest: float | None = Field(description="the newest daily value")
    latest_date: dt.date | None
    history_from: dt.date | None = Field(description="first day with a value")
    mean7: float | None = Field(description="7-day mean on today")
    mean28: float | None
    median28: float | None = Field(description="personal normal (median of the 28 days before today)")
    mad28: float | None
    change: RecentChangeDTO
    monthly: list[MonthValueDTO] = Field(description="calendar-month means, oldest first")


class HealthOverviewDTO(BaseModel):
    """GET /wellness/health – every §12.1 metric with its trend summary."""

    today: dt.date
    first_date: dt.date | None = Field(description="first day with any health data")
    metrics: list[HealthMetricDTO]
    missing_history: list[str] = Field(
        description="metrics starting > 28 days after first_date (run `training recompute`, §12.1)"
    )


class HealthPointDTO(BaseModel):
    date: dt.date
    value: float | None
    mean7: float | None
    median28: float | None
    mad28: float | None
    pct: float | None = Field(description="7-day mean relative to the normal, % (§12.2)")


class HealthSeriesDTO(BaseModel):
    key: str
    label: str
    unit: str
    better: str | None
    points: list[HealthPointDTO]


class HealthRelationshipDTO(BaseModel):
    x: str
    y: str
    lag: int = Field(description="0 = same day, 1 = y on the next day")
    n: int
    rho: float
    ci_low: float
    ci_high: float
    p: float
    finding: bool = Field(description="|ρ| ≥ 0.2 and passes Benjamini–Hochberg (q = 0.05)")
    contrast: float | None = Field(description="mean y (raw unit of y) top − bottom quartile of x deviation")
    text: str = Field(description="plain Slovak sentence")


class HealthRelationshipsDTO(BaseModel):
    """GET /wellness/health/relationships – findings first (§12.3)."""

    tested: int = Field(description="pairs with n ≥ 30")
    findings: list[HealthRelationshipDTO]
    others: list[HealthRelationshipDTO] = Field(
        description="the strongest non-findings (max 20), for context"
    )
