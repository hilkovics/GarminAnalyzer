"""Prediction DTOs (METRICS §11.5); re-exported by `services.dto`. Pace as speed m/s, sleep in seconds."""

import datetime as dt

from pydantic import BaseModel, Field


class SleepEffectDTO(BaseModel):
    """The personal effect of last night's sleep on the pace at the reference HR (TSB held constant)."""

    status: str = Field(description='"insufficient" (n < 30) | "uncertain" (CI contains 0) | "reliable"')
    n: int = Field(description="run days with pace at reference HR, last night's sleep and TSB")
    min_n: int
    slope: float | None = Field(description="m/s per hour of sleep")
    ci_low: float | None
    ci_high: float | None
    sleep_typ_s: float | None = Field(description="median sleep of those days")
    pace_typ: float | None = Field(description="median pace at reference HR of those days, m/s")


class SleepNoteDTO(BaseModel):
    sleep_s: float = Field(description="last night's sleep")
    delta_s_per_km: int = Field(description="expected pace change today, + = slower")
    text: str


class OutlookDayDTO(BaseModel):
    date: dt.date
    readiness: float | None = Field(description="expected readiness 0–100 from typical wellness and load")
    band: str | None
    load: float = Field(description="typical load of the weekday, TSS-equivalent points")
    tsb: float
    sleep_s: float | None = Field(description="typical sleep of the weekday")
    sleep_score: float | None
    rhr: float | None
    body_battery_wake: float | None
    available: bool = Field(description="not a rest day in the preferred days")
    best: bool = Field(description="one of the best days for quality (§11.5)")


class ForecastDTO(BaseModel):
    """GET /plan/forecast – the morning note and the 7-day outlook (orientation only)."""

    date: dt.date
    sleep_effect: SleepEffectDTO
    note: SleepNoteDTO | None = Field(description="null when the effect is not reliable or below 3 s/km")
    days: list[OutlookDayDTO] = Field(description="today + 1 … today + 7")
