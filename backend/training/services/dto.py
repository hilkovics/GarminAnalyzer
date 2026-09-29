"""Pydantic DTOs shared by Streamlit and FastAPI (CLAUDE.md rule 3). Field names snake_case; units in
the field descriptions. Phase 2 adds DiagnosticsDTO; phase 3 adds the rest (PLAN §5)."""

import datetime as dt

from pydantic import BaseModel, Field


class LoadSanityDTO(BaseModel):
    """METRICS §2.5: Pearson r between load_primary and Garmin training load."""

    r: float | None = Field(description="Pearson correlation coefficient, null if n < 3")
    n: int = Field(description="activities with both values")
    status: str = Field(description='"good" (r > 0.8) | "fair" | "warning" (r < 0.7) | "insufficient"')


class LoadDivergenceDTO(BaseModel):
    garmin_id: int
    local_date: dt.date
    sport: str
    hrtss: float = Field(description="TSS-equivalent points")
    rtss: float = Field(description="TSS-equivalent points")
    diff_pct: float = Field(description="|hrTSS − rTSS| / min(hrTSS, rTSS) · 100 (relative to the smaller)")


class DiagnosticsDTO(BaseModel):
    last_activity_sync: dt.date | None
    last_wellness_date: dt.date | None
    backfill_cursor: dt.date | None
    pending_activities: int
    pending_wellness_days: int
    failed_activities: list[int]
    failed_wellness_days: list[dt.date]
    activities: int
    activities_with_metrics: int
    activities_without_threshold: int = Field(
        description="activities with no threshold record valid at their date"
    )
    activities_without_load: int = Field(
        description="activities whose load_primary is null (no LTHR, no HR, …)"
    )
    low_confidence_share: float | None = Field(description="share of activities flagged low_confidence (0–1)")
    load_sanity: LoadSanityDTO
    hrtss_rtss_divergent: list[LoadDivergenceDTO] = Field(
        description="runs where hrTSS and rTSS differ by > 40 % of the smaller value (threshold check)"
    )
