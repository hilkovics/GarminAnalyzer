"""Phase-7 DTOs (Telegram morning message, weekly AI report); re-exported by `services.dto`.

Internal units only (seconds, TSS-equivalent points); the report text itself is Slovak prose.
"""

import datetime as dt

from pydantic import BaseModel, Field

from training.services.dto_plan import GoalDTO, WeekPlanDTO
from training.services.dto_wellness import CorrelationDTO

# --- morning message ----------------------------------------------------------------------------------------


class MorningMessageDTO(BaseModel):
    """The plain-text Telegram morning message and the numbers it was built from."""

    date: dt.date
    text: str = Field(description="plain Slovak text, at most ~12 lines")
    readiness: float | None = Field(description="0–100; null when there is not enough wellness data")
    readiness_band: str | None = Field(description='"green" | "yellow" | "red"')
    workout_name: str
    yesterday_load: float | None = Field(description="load_total of yesterday, TSS-equivalent points")
    tsb: float | None = Field(description="TSB of yesterday")


# --- weekly report ------------------------------------------------------------------------------------------


class ReportActivityDTO(BaseModel):
    date: dt.date
    sport: str = Field(description='"run" | "bike" | "other"')
    duration_s: float | None
    load: float | None = Field(description="primary load, TSS-equivalent points; null = unknown")


class ReportPmcDTO(BaseModel):
    """PMC values of one day (METRICS §4)."""

    date: dt.date
    ctl: float | None
    atl: float | None
    tsb: float | None
    ramp_rate: float | None


class ReportReadinessDTO(BaseModel):
    date: dt.date
    score: float | None = Field(description="0–100; null when unavailable")
    band: str | None


class WeeklyReportInputsDTO(BaseModel):
    """Everything the weekly prompt is built from (the LLM sees nothing else)."""

    today: dt.date
    activities: list[ReportActivityDTO] = Field(description="last 7 days (today − 6 … today), date ascending")
    pmc_now: ReportPmcDTO | None
    pmc_week_ago: ReportPmcDTO | None
    readiness: list[ReportReadinessDTO] = Field(description="last 7 days, date ascending")
    findings: list[CorrelationDTO] = Field(description="top 3 sleep findings by |ρ|")
    this_week: WeekPlanDTO
    next_week: WeekPlanDTO
    goal: GoalDTO | None


class ReportDTO(BaseModel):
    """A stored weekly report (`reports_dir/YYYY-Www.md`)."""

    week: str = Field(description='ISO week, e.g. "2026-W40"')
    generated_at: dt.datetime = Field(description="UTC")
    model: str
    markdown: str = Field(description="the report body (Markdown, without the file header)")
