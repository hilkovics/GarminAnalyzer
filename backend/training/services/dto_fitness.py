"""Fitness DTOs (PMC, polarization, weekly aggregates, dashboard – METRICS §4); re-exported by `dto`."""

import datetime as dt

from pydantic import BaseModel, Field

# --- fitness ------------------------------------------------------------------------------------------------


class PmcPointDTO(BaseModel):
    date: dt.date
    load_total: float
    load_run: float
    load_bike: float
    ctl: float | None
    atl: float | None
    tsb: float | None
    acwr: float | None
    acwr_band: str | None = Field(description='"under" | "optimal" | "caution" | "danger"')
    monotony: float | None
    strain: float | None
    ramp_rate: float | None
    ramp_warning: bool = Field(description="ramp_rate > 6 (METRICS §4)")
    warming_up: bool = Field(description="within the first 90 days of the series (§4)")


class PmcDTO(BaseModel):
    points: list[PmcPointDTO] = Field(description="daily, date ascending")
    series_start: dt.date | None
    warming_up_until: dt.date | None = Field(description="series_start + 89 days")
    latest: PmcPointDTO | None


class PolarizationDTO(BaseModel):
    low: float = Field(description="share Z1–Z2")
    mid: float = Field(description="share Z3")
    high: float = Field(description="share Z4–Z5")


class WeeklyDTO(BaseModel):
    week_start: dt.date = Field(description="Monday of the ISO week")
    iso_year: int
    iso_week: int
    sport: str = Field(description='"run" | "bike" | "other" | "all"')
    n_activities: int
    load: float
    duration_s: float
    distance_m: float
    elev_gain_m: float
    time_in_zone: dict[str, float] = Field(description='HR zone seconds {"1": s, …, "5": s}')
    polarization: PolarizationDTO | None


class DashboardDTO(BaseModel):
    today: dt.date
    week_start: dt.date
    this_week: list[WeeklyDTO] = Field(description="per sport + all (zeros if nothing yet)")
    last4_avg: list[WeeklyDTO] = Field(description="per sport + all: mean of the 4 previous ISO weeks")
    pmc: PmcDTO = Field(description="last 42 days")
    latest: PmcPointDTO | None
    last_sync: dt.date | None
    sync_stale: bool = Field(description="last successful sync older than 36 h (PLAN phase 8 health)")
    last_successful_run: dt.datetime | None = Field(
        default=None, description="UTC finish of the newest ok `training morning` run; null if none"
    )
    last_run_ok: bool | None = Field(
        default=None, description="outcome of the newest morning run; null when there never was one"
    )
    morning_run_stale: bool = Field(
        default=False,
        description="morning runs exist but none succeeded in the last 36 h (false when there never was one)",
    )
