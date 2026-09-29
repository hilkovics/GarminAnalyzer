"""Phase-5 DTOs (wellness, readiness, correlations – METRICS §8–§9); re-exported by `services.dto`."""

import datetime as dt

from pydantic import BaseModel, Field

# --- wellness, readiness, correlations (phase 5, METRICS §8–§9) ---------------------------------------------


class BaselineDTO(BaseModel):
    """Trailing 28-day baseline of one wellness field (METRICS §8, day itself excluded)."""

    median: float | None = Field(description="median of the valid values of D-28 … D-1; null with < 7 values")
    mad: float | None = Field(description="raw median absolute deviation (no scaling), same window")


class WellnessBaselinesDTO(BaseModel):
    rhr: BaselineDTO = Field(description="bpm")
    sleep_s: BaselineDTO = Field(description="seconds")
    sleep_score: BaselineDTO = Field(description="Garmin sleep score points")
    body_battery_wake: BaselineDTO = Field(description="Body Battery points")


class WellnessDayDTO(BaseModel):
    """One wellness row: the night that ends on the morning of `date`, RHR / Body Battery of `date`."""

    date: dt.date
    sleep_start: dt.datetime | None = Field(description="UTC")
    sleep_end: dt.datetime | None = Field(description="UTC")
    sleep_s: float | None = Field(description="seconds")
    deep_s: float | None = Field(description="seconds")
    light_s: float | None = Field(description="seconds")
    rem_s: float | None = Field(description="seconds")
    awake_s: float | None = Field(description="seconds")
    sleep_score: float | None = Field(description="Garmin sleep score, 0–100")
    rhr: float | None = Field(description="resting HR, bpm")
    body_battery_wake: float | None
    body_battery_min: float | None
    stress_avg: float | None
    steps: int | None
    weight_kg: float | None
    baselines: WellnessBaselinesDTO = Field(
        description="baselines valid for this day (computed over the full history)"
    )
    sleep_debt_7_s: float | None = Field(
        description="7-night sleep debt, seconds (METRICS §9); negative = surplus; null with < 5 valid nights"
    )
    readiness: float | None = Field(description="persisted daily_load.readiness, unrounded, 0–100")
    readiness_band: str | None = Field(description='"green" | "yellow" | "red"')


class WellnessDTO(BaseModel):
    """GET /wellness/daily – wellness rows (only days that have one), date ascending."""

    days: list[WellnessDayDTO]
    date_from: dt.date | None = Field(description="requested start, else the first returned day")
    date_to: dt.date | None = Field(description="requested end, else the last returned day")


class ReadinessComponentDTO(BaseModel):
    name: str = Field(description='"rhr" | "sleep" | "body_battery" | "form"')
    score: float | None = Field(description="component score 0–100; null when the input is missing")
    weight: float | None = Field(description="renormalized weight (the used ones sum to 1); null if missing")
    value: float | None = Field(
        description="raw input: bpm (rhr), sleep score points or seconds (sleep, see unit), Body Battery "
        "points, TSB (form)"
    )
    baseline: float | None = Field(
        description="28-day median of the input (context only; the RHR score and the sleep fallback use it)"
    )
    unit: str = Field(description='unit of value/baseline: "bpm" | "score" | "s" | "points" | "TSB"')


class ReadinessDTO(BaseModel):
    """GET /wellness/readiness/{date} – readiness of one day (METRICS §8)."""

    date: dt.date
    available: bool = Field(description="false when the day has no wellness component (no score)")
    score: float | None = Field(description="0–100, unrounded (display truncated to an integer)")
    band: str | None = Field(description='"green" (≥ 70) | "yellow" (45–69) | "red" (< 45)')
    components: list[ReadinessComponentDTO] = Field(description="always the four components, in table order")
    message: str = Field(description="Slovak advice for the band")


class CorrelationDTO(BaseModel):
    """One (sport, predictor, outcome) finding (METRICS §9). Null statistics are null."""

    sport: str = Field(description='"run" | "bike"')
    predictor: str = Field(description='predictor column, e.g. "sleep_s_lag0", "sleep_debt_7"')
    predictor_base: str = Field(description='predictor without variant, e.g. "sleep_s"')
    variant: str = Field(description='"lag0" (night before) | "lag1" (two nights before) | "mean3"')
    outcome: str = Field(description='"ef" | "decoupling_pct" | "pace_at_ref_hr_day" | "rpe_residual"')
    n: int
    status: str = Field(description='"ok" | "insufficient_data" (n < 30)')
    rho: float | None = Field(description="Spearman ρ")
    p: float | None
    ci_low: float | None = Field(description="bootstrap 95 % CI of ρ")
    ci_high: float | None
    partial_n: int | None
    partial_rho: float | None = Field(description="Spearman on OLS residuals after TSB, ATL[D-1], load[D-1]")
    partial_p: float | None
    partial_ci_low: float | None
    partial_ci_high: float | None
    q_contrast: float | None = Field(description="mean outcome top quartile − bottom quartile (outcome unit)")
    q_ci_low: float | None
    q_ci_high: float | None
    q_n_bottom: int | None
    q_n_top: int | None
    uncertain: bool = Field(description="the headline CI contains 0 (or there is none)")
    headline_rho: float | None = Field(description="partial ρ if present, else raw ρ (sort key)")
    sentence: str = Field(description="one plain-Slovak sentence describing the finding")


class CorrelationsDTO(BaseModel):
    """GET /wellness/correlations – findings sorted by |headline ρ| plus the pairs without enough data."""

    sports: list[str] = Field(description="sports covered by this response")
    findings: list[CorrelationDTO] = Field(description="status ok, sorted by |headline ρ| descending")
    insufficient: list[CorrelationDTO] = Field(description="status insufficient_data; n is reported")
    min_n: int = Field(description="minimum n for a finding (30)")
    caveat: str = Field(description="fixed Slovak caveat text (METRICS §9.5); always show it")
    n_days: dict[str, int] = Field(description="qualifying days (dataset rows) per sport")
