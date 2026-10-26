"""Predictions of the coach "Kondícia" (METRICS §11.5): the personal sleep → pace effect with its morning
note, and the 7-day readiness outlook with the best days for quality. Pure functions – no I/O.

Units: pace as speed m/s, sleep in seconds (hours only inside the model), load in TSS-equivalent points.
"""

import math
import statistics
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from training.analysis.readiness import GREEN_FROM, band, readiness
from training.metrics.pmc import ATL_DAYS, CTL_DAYS

MIN_ROWS = 30
N_BOOT = 1000
MAX_NAN_SHARE = 0.10
NOTE_MIN_S_PER_KM = 3.0
OUTLOOK_DAYS = 7
TYPICAL_WEEKS = 8
TYPICAL_MIN_VALUES = 3
BEST_DAYS = 2
WELLNESS_FIELDS = ("sleep_score", "sleep_s", "rhr", "body_battery_wake")

INSUFFICIENT, UNCERTAIN, RELIABLE = "insufficient", "uncertain", "reliable"


# --- sleep effect on pace -----------------------------------------------------------------------------------


@dataclass(frozen=True)
class SleepEffect:
    status: str  # "insufficient" | "uncertain" | "reliable"
    n: int
    slope: float | None = None  # m/s per hour of sleep, TSB held constant
    ci_low: float | None = None
    ci_high: float | None = None
    sleep_typ_s: float | None = None
    pace_typ: float | None = None  # m/s


@dataclass(frozen=True)
class SleepNote:
    sleep_s: float
    delta_s_per_km: int  # + = slower
    text: str


def _slope(y: np.ndarray, sleep_h: np.ndarray, tsb: np.ndarray) -> float:
    design = np.column_stack([np.ones_like(y), sleep_h, tsb])
    if np.linalg.matrix_rank(design) < design.shape[1]:
        return math.nan
    coef, *_ = np.linalg.lstsq(design, y, rcond=None)
    return float(coef[1])


def sleep_effect(dataset: pd.DataFrame, *, n_boot: int = N_BOOT, seed: int = 0) -> SleepEffect:
    """§11.5 OLS `pace = a + b · sleep_h + c · tsb` on the §9 run dataset, with a bootstrap CI of `b`."""
    columns = ["pace_at_ref_hr_day", "sleep_s_lag0", "tsb"]
    rows = dataset[columns].apply(pd.to_numeric, errors="coerce").dropna() if len(dataset) else dataset
    n = len(rows)
    if n < MIN_ROWS:
        return SleepEffect(INSUFFICIENT, n)
    y = rows["pace_at_ref_hr_day"].to_numpy(dtype=float)
    sleep_h = rows["sleep_s_lag0"].to_numpy(dtype=float) / 3600.0
    tsb = rows["tsb"].to_numpy(dtype=float)
    slope = _slope(y, sleep_h, tsb)
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(n_boot):
        idx = rng.integers(0, n, n)
        boots.append(_slope(y[idx], sleep_h[idx], tsb[idx]))
    values = np.array(boots)
    valid = values[~np.isnan(values)]
    typical = {"sleep_typ_s": float(np.median(sleep_h)) * 3600.0, "pace_typ": float(np.median(y))}
    if math.isnan(slope) or len(valid) < (1 - MAX_NAN_SHARE) * n_boot:
        return SleepEffect(UNCERTAIN, n, None if math.isnan(slope) else slope, **typical)
    low, high = (float(v) for v in np.percentile(valid, [2.5, 97.5]))
    status = RELIABLE if low > 0 or high < 0 else UNCERTAIN
    return SleepEffect(status, n, slope, low, high, **typical)


def _hm(seconds: float) -> str:
    minutes = round(abs(seconds) / 60)
    return f"{minutes // 60}:{minutes % 60:02d}"


def sleep_note(effect: SleepEffect, sleep_s: float | None) -> SleepNote | None:
    """§11.5 morning note for last night's `sleep_s`; None when not reliable or the effect is < 3 s/km."""
    if effect.status != RELIABLE or sleep_s is None or not math.isfinite(sleep_s):
        return None
    assert effect.slope is not None and effect.sleep_typ_s is not None and effect.pace_typ is not None
    dv = effect.slope * (sleep_s - effect.sleep_typ_s) / 3600.0
    if effect.pace_typ + dv <= 0:
        return None
    delta = 1000.0 / (effect.pace_typ + dv) - 1000.0 / effect.pace_typ
    if abs(delta) < NOTE_MIN_S_PER_KM:
        return None
    seconds = math.floor(abs(delta) + 0.5)
    diff = sleep_s - effect.sleep_typ_s
    sign = "+" if diff >= 0 else "−"
    head = (
        f"Po {_hm(sleep_s)} spánku ({sign}{_hm(diff)} oproti zvyčajným {_hm(effect.sleep_typ_s)}) "
        f"býva tvoje tempo pri rovnakom tepe o ~{seconds} s/km"
    )
    tail = "pomalšie – drž sa tepu, nie tempa." if delta > 0 else "rýchlejšie – tempo môže dnes ísť ľahšie."
    return SleepNote(sleep_s, seconds if delta > 0 else -seconds, f"{head} {tail}")


# --- 7-day outlook ------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class OutlookDay:
    day: date
    readiness: float | None
    band: str | None
    load: float
    tsb: float
    typical: dict[str, float | None]


def _same_weekday(day: date, today: date) -> list[date]:
    """The days with `day`'s weekday in `today − 56 … today − 1`."""
    first = today - timedelta(days=TYPICAL_WEEKS * 7)
    offset = (day.weekday() - first.weekday()) % 7
    return [
        first + timedelta(days=offset + 7 * k)
        for k in range(TYPICAL_WEEKS)
        if first + timedelta(days=offset + 7 * k) < today
    ]


def _median(values: Iterable[object], minimum: int) -> float | None:
    clean = [float(v) for v in values if v is not None and isinstance(v, (int, float)) and math.isfinite(v)]
    return statistics.median(clean) if len(clean) >= minimum else None


def typical_wellness(
    wellness: Mapping[date, Mapping[str, object]], day: date, today: date
) -> dict[str, float | None]:
    """§11.5 typical wellness of `day`: per field the median of the same weekday over 8 weeks (≥ 3 values)."""
    days = _same_weekday(day, today)
    return {
        field: _median((wellness.get(d, {}).get(field) for d in days), TYPICAL_MIN_VALUES)
        for field in WELLNESS_FIELDS
    }


def typical_load(loads: Mapping[date, float], day: date, today: date) -> float:
    """§11.5 typical load of `day`: median `load_total` of the same weekday over 8 weeks (missing days 0)."""
    return float(statistics.median(float(loads.get(d, 0.0) or 0.0) for d in _same_weekday(day, today)))


def outlook(
    *,
    today: date,
    ctl_prev: float,
    atl_prev: float,
    load_today: float,
    wellness: Mapping[date, Mapping[str, object]],
    loads: Mapping[date, float],
    rhr_median28: float | None,
    sleep_s_median28: float | None,
) -> list[OutlookDay]:
    """§11.5: readiness of the next 7 days from typical wellness and load, CTL/ATL carried forward (§4)."""
    ctl = ctl_prev + (load_today - ctl_prev) / CTL_DAYS
    atl = atl_prev + (load_today - atl_prev) / ATL_DAYS
    out = []
    for i in range(1, OUTLOOK_DAYS + 1):
        day = today + timedelta(days=i)
        tsb = ctl - atl
        typical = typical_wellness(wellness, day, today)
        result = readiness(
            rhr=typical["rhr"],
            rhr_median28=rhr_median28,
            sleep_score=typical["sleep_score"],
            sleep_s=typical["sleep_s"],
            sleep_s_median28=sleep_s_median28,
            body_battery_wake=typical["body_battery_wake"],
            tsb=tsb,
        )
        load = typical_load(loads, day, today)
        out.append(OutlookDay(day, result.score, band(result.score), load, tsb, typical))
        ctl += (load - ctl) / CTL_DAYS
        atl += (load - atl) / ATL_DAYS
    return out


def best_days(days: list[OutlookDay], available: Iterable[date]) -> list[date]:
    """§11.5: at most 2 available green days, highest readiness first (ties: the earlier day)."""
    allowed = set(available)
    green = [d for d in days if d.day in allowed and d.readiness is not None and d.readiness >= GREEN_FROM]
    return [d.day for d in sorted(green, key=lambda d: (-(d.readiness or 0.0), d.day))[:BEST_DAYS]]
