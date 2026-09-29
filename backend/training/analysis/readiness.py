"""Readiness score 0–100 – METRICS §8 (phase 5).

Pure functions over pandas/numpy; no I/O.

# METRICS §8
#   Readiness (0–100) = weighted mean of available component scores (weights renormalized if a component
#   is missing):
#     RHR           0.30   100 − 12.5 · max(0, rhr − rhr_median28)
#     Sleep         0.30   sleep_score; fallback 100 · sleep_s / max(7.5 h, sleep_s_median28)
#     Body Battery  0.20   body_battery_wake
#     Form          0.20   50 + 2 · TSB (TSB from §4, today's value)
#   (each score clamped 0–100)
#   Bands: ≥ 70 green, 45–69 yellow, < 45 red.
# Clarified 2026-09-29 (phase 5, proposed):
#   Components: RHR is null if rhr or its median is null. Sleep uses sleep_score if present, else the
#   fallback if sleep_s is present (a null median counts as 7.5 h). Body Battery is body_battery_wake.
#   Form uses TSB[D] from §4 (already the state entering the day). Each score is clamped to 0–100.
#   Readiness is computed for every day with at least one wellness component (RHR, Sleep or Body Battery).
#   Form alone does not produce a score. Missing components drop out and the remaining weights are
#   renormalized to sum 1 (the reported weights are empty when there is no score). The value is stored
#   unrounded; bands are applied to that unrounded value; the UI displays it truncated to an integer.

Bands are read on the unrounded score: `score ≥ 70` green, `45 ≤ score < 70` yellow, `score < 45` red.
"""

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# METRICS §8 constants (do not change without changing METRICS.md first).
WEIGHTS = {"rhr": 0.30, "sleep": 0.30, "body_battery": 0.20, "form": 0.20}
WELLNESS_COMPONENTS = ("rhr", "sleep", "body_battery")  # at least one is needed for a score
RHR_POINTS_PER_BPM = 12.5
SLEEP_FALLBACK_FLOOR_S = 7.5 * 3600.0
FORM_BASE = 50.0
FORM_POINTS_PER_TSB = 2.0
GREEN_FROM = 70.0
YELLOW_FROM = 45.0
SCORE_MIN = 0.0
SCORE_MAX = 100.0

FRAME_COLUMNS = ("readiness", "band", "rhr_score", "sleep_score_c", "body_battery_score", "form_score")
_COMPONENT_COLUMNS = {
    "rhr": "rhr_score",
    "sleep": "sleep_score_c",
    "body_battery": "body_battery_score",
    "form": "form_score",
}
_WELLNESS_INPUTS = ("rhr", "rhr_median28", "sleep_score", "sleep_s", "sleep_s_median28", "body_battery_wake")


@dataclass(frozen=True)
class ReadinessResult:
    """Readiness of one day (METRICS §8).

    `components` has all four keys (`rhr`, `sleep`, `body_battery`, `form`), None when missing.
    `weights` holds the renormalized weights (sum 1) of the components that entered the score; it is
    empty when there is no score.
    """

    score: float | None
    band: str | None
    components: dict[str, float | None] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=dict)


def band(score: float | None) -> str | None:
    """Readiness band of the unrounded score (METRICS §8): ≥ 70 green, ≥ 45 yellow, else red."""
    value = _clean(score)
    if value is None:
        return None
    if value >= GREEN_FROM:
        return "green"
    if value >= YELLOW_FROM:
        return "yellow"
    return "red"


def readiness(
    *,
    rhr: float | None,
    rhr_median28: float | None,
    sleep_score: float | None,
    sleep_s: float | None,
    sleep_s_median28: float | None,
    body_battery_wake: float | None,
    tsb: float | None,
) -> ReadinessResult:
    """Readiness 0–100 from the day's wellness row, its §8 baselines and `TSB[D]` (METRICS §8).

    NaN counts as None. The score is the weighted mean of the present components with the weights
    renormalized to sum 1; it is None unless RHR, Sleep or Body Battery is present (Form alone gives
    no score). Unrounded.
    """
    components = {
        "rhr": _rhr_score(_clean(rhr), _clean(rhr_median28)),
        "sleep": _sleep_score(_clean(sleep_score), _clean(sleep_s), _clean(sleep_s_median28)),
        "body_battery": _clamp_or_none(_clean(body_battery_wake)),
        "form": _form_score(_clean(tsb)),
    }
    if all(components[c] is None for c in WELLNESS_COMPONENTS):
        return ReadinessResult(score=None, band=None, components=components, weights={})
    present = {k: WEIGHTS[k] for k, v in components.items() if v is not None}
    total = sum(present.values())
    weights = {k: w / total for k, w in present.items()}
    score = sum(weights[k] * components[k] for k in weights)  # type: ignore[operator]
    return ReadinessResult(score=score, band=band(score), components=components, weights=weights)


def readiness_frame(wellness: pd.DataFrame, tsb: pd.Series) -> pd.DataFrame:
    """Readiness for every wellness date (METRICS §8).

    `wellness` is the output of `analysis.wellness.with_baselines` (absent input columns count as null);
    `tsb` is the §4 TSB, indexed by date (`datetime.date` or midnight timestamps). A date without a TSB
    value has no Form component. Returns one row per wellness date (same index) with the columns
    `readiness` (float, NaN = no score), `band` (object, None = no score) and the component scores
    `rhr_score`, `sleep_score_c`, `body_battery_score`, `form_score` (float, NaN = missing).
    """
    n = len(wellness)
    inputs = {c: _column(wellness, c) for c in _WELLNESS_INPUTS}
    tsb_values = _tsb_on(wellness.index, tsb)
    scores = np.full(n, np.nan)
    bands: list[str | None] = [None] * n
    comps = {col: np.full(n, np.nan) for col in _COMPONENT_COLUMNS.values()}
    for i in range(n):
        result = readiness(**{c: float(inputs[c][i]) for c in _WELLNESS_INPUTS}, tsb=float(tsb_values[i]))
        if result.score is not None:
            scores[i] = result.score
        bands[i] = result.band
        for key, col in _COMPONENT_COLUMNS.items():
            value = result.components[key]
            if value is not None:
                comps[col][i] = value
    out = pd.DataFrame({"readiness": scores, **comps}, index=wellness.index)
    out["band"] = pd.Series(bands, index=wellness.index, dtype=object)  # None stays None (not NaN)
    return out[list(FRAME_COLUMNS)]


# ---------------------------------------------------------------------------------------------------------
# component scores


def _rhr_score(rhr: float | None, median: float | None) -> float | None:
    if rhr is None or median is None:
        return None
    return _clamp(SCORE_MAX - RHR_POINTS_PER_BPM * max(0.0, rhr - median))


def _sleep_score(sleep_score: float | None, sleep_s: float | None, median: float | None) -> float | None:
    if sleep_score is not None:
        return _clamp(sleep_score)
    if sleep_s is None:
        return None
    floor = SLEEP_FALLBACK_FLOOR_S if median is None else max(SLEEP_FALLBACK_FLOOR_S, median)
    return _clamp(100.0 * sleep_s / floor)


def _form_score(tsb: float | None) -> float | None:
    if tsb is None:
        return None
    return _clamp(FORM_BASE + FORM_POINTS_PER_TSB * tsb)


# ---------------------------------------------------------------------------------------------------------
# helpers


def _clamp(value: float) -> float:
    return min(SCORE_MAX, max(SCORE_MIN, value))


def _clamp_or_none(value: float | None) -> float | None:
    return None if value is None else _clamp(value)


def _clean(value: float | None) -> float | None:
    """None for None / NaN / pd.NA, else a float."""
    if value is None or value is pd.NA:
        return None
    number = float(value)
    return None if math.isnan(number) else number


def _column(frame: pd.DataFrame, name: str) -> np.ndarray:
    if name not in frame.columns:
        return np.full(len(frame), np.nan)
    return pd.to_numeric(frame[name], errors="coerce").astype(float).to_numpy()


def _tsb_on(index: pd.Index, tsb: pd.Series) -> np.ndarray:
    """TSB values on the dates of `index` (NaN where TSB has no value for that date)."""
    if len(index) == 0:
        return np.array([], dtype=float)
    if len(tsb) == 0:
        return np.full(len(index), np.nan)
    by_day = pd.Series(
        pd.to_numeric(tsb, errors="coerce").astype(float).to_numpy(),
        index=pd.DatetimeIndex([pd.Timestamp(v).normalize() for v in tsb.index]),
    )
    if by_day.index.has_duplicates:
        raise ValueError("tsb index has duplicate dates")
    wanted = pd.DatetimeIndex([pd.Timestamp(v).normalize() for v in index])
    return by_day.reindex(wanted).to_numpy(dtype=float)
