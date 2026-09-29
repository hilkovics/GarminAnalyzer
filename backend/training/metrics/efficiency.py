"""Steady state, Efficiency Factor, aerobic decoupling – METRICS §5 (phase 4).

# METRICS §5.1
An activity is `steady_state` if, after dropping the first 600 s: `moving_s ≥ 1800`, `hr_coverage ≥ 0.9`,
mean HR in `[0.70, 0.88]·lthr`, std of 60 s-averaged HR `< 6 bpm`, and no continuous ≥ 60 s stretch with
`hr > 0.95·lthr`.
(Clarified 2026-09-29, phase 4: evaluated on the kept samples that remain after dropping the first 600 s of
moving time; "60 s-averaged HR" = means of consecutive non-overlapping 60-sample blocks, last partial block
dropped, blocks with < 30 valid HR skipped, population std. The stretch counts consecutive kept samples with
valid HR above the limit – a NaN breaks it. No lthr → not steady. Raw HR, no lag.)

# METRICS §5.2
On steady-state runs, after dropping the first 600 s and walking samples:
`EF = mean(gap_speed) [m/min] / mean(hr) [bpm]`. Trend: 28-day rolling median over steady-state runs.
(Clarified: samples = kept, after the first 600 s, not `is_slow`, §0.6 lag applied, only pairs where both
`gap_speed` and lagged HR are valid. m/min = m/s · 60. Trend on day d = median EF of the steady-state runs
with `local_date` in [d − 27, d]; null if none.)

# METRICS §5.3
Same samples as EF, split into two equal halves: `EF1`, `EF2`. `decoupling_pct = (EF1 − EF2) / EF1 · 100`.
Bands: `< 5` good, `5–10` moderate, `> 10` poor. (Clarified: first ⌊n/2⌋ vs the rest; needs ≥ 600
samples, else null; `[5, 10]` moderate.)

# METRICS §5.4
Bike: only samples with `|grade| ≤ 0.01`, speed `≥ 4 m/s`, after 600 s, no stops within ±30 s.
`EF_bike = mean(speed) [m/min] / mean(hr)`. Steady state as §5.1, decoupling as §5.3 on the same samples.
(Clarified: a stop is a pause – a gap in `t` between consecutive kept samples – or a slow sample (bike
`< 2.0 m/s`); every sample within 30 s (by `t`) of a stop is excluded. Uses `speed`, not GAP; lag as §5.2.)

# METRICS §0.6
`hr_lagged[i] = hr[i + 30]` over the kept samples in time order; the last 30 samples have no partner.

Interpretation (see the module tests): a pause's "stop" instants are its missing whole seconds
`t_a + 1 .. t_b − 1`, and "within 30 s" is inclusive (`|Δt| ≤ 30`). So a slow sample excludes 61 samples
(itself ± 30) and a pause excludes the 30 kept samples on each side.

Pure functions, no I/O.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import numpy as np
import pandas as pd

from training.metrics.preprocess import HR_LAG_S, SPORTS, Preprocessed, lag_hr

WARMUP_S = 600  # §5.1/§5.2: first 600 s of moving time dropped
MIN_STEADY_S = 1800  # §5.1 moving_s after the warm-up
MIN_STEADY_COVERAGE = 0.9  # §5.1
STEADY_HR_BAND = (0.70, 0.88)  # §5.1, × lthr, inclusive
BLOCK_S = 60  # §5.1 60 s-averaged HR
BLOCK_MIN_VALID = 30  # §5.1 clarified
MAX_BLOCK_STD = 6.0  # §5.1, strict <
HIGH_HR_FRACTION = 0.95  # §5.1, × lthr, strict >
MAX_HIGH_STRETCH_S = 60  # §5.1: a stretch of ≥ 60 samples fails
MIN_DECOUPLING_SAMPLES = 600  # §5.3 clarified
DECOUPLING_BANDS = (5.0, 10.0)  # §5.3: < 5 good, [5, 10] moderate, > 10 poor
BIKE_MAX_ABS_GRADE = 0.01  # §5.4
BIKE_MIN_SPEED = 4.0  # §5.4, m/s
BIKE_STOP_MARGIN_S = 30  # §5.4, ± s around a stop
TREND_WINDOW_DAYS = 28  # §5.2: [d − 27, d]
EF_SAMPLE_COLUMNS: tuple[str, ...] = ("t", "speed", "hr")


@dataclass(frozen=True)
class EfficiencyResult:
    """METRICS §5.1–§5.4 for one activity.

    `ef` (m/min per bpm) and `decoupling_pct` are None unless `steady_state` (and the EF sample set is
    non-empty / has ≥ 600 samples). `n_samples` is the size of the EF sample set (0 for "other").
    """

    steady_state: bool
    ef: float | None
    decoupling_pct: float | None
    decoupling_band: str | None
    n_samples: int


def is_steady_state(prep: Preprocessed, lthr: float | None) -> bool:
    """METRICS §5.1 on the kept samples after the first 600 s (raw HR, no lag)."""
    if lthr is None:
        return False
    hr = prep.samples["hr"].to_numpy(dtype=float)[WARMUP_S:]
    n = len(hr)
    if n < MIN_STEADY_S:
        return False
    valid = ~np.isnan(hr)
    n_valid = int(np.count_nonzero(valid))
    if n_valid / n < MIN_STEADY_COVERAGE:
        return False
    mean_hr = float(np.mean(hr[valid]))
    lo, hi = STEADY_HR_BAND
    if not (lo * lthr <= mean_hr <= hi * lthr):
        return False
    block_means = _block_means(hr)
    if len(block_means) == 0 or float(np.std(block_means)) >= MAX_BLOCK_STD:
        return False
    return _longest_run(valid & (hr > HIGH_HR_FRACTION * lthr)) < MAX_HIGH_STRETCH_S


def ef_samples(prep: Preprocessed, *, sport: str) -> pd.DataFrame:
    """The §5.2 (run) / §5.4 (bike) EF sample set: columns `t, speed, hr` with lagged HR (§0.6).

    `speed` is `gap_speed` for runs and `speed` for bikes. "other" has no EF sample set (empty frame).
    """
    _check_sport(sport)
    s = prep.samples
    n = len(s)
    empty = pd.DataFrame({c: pd.Series(dtype=np.int64 if c == "t" else float) for c in EF_SAMPLE_COLUMNS})
    if sport == "other" or n == 0:
        return empty
    t = s["t"].to_numpy(dtype=np.int64)
    hr_lag = lag_hr(s["hr"].to_numpy(dtype=float), HR_LAG_S)
    speed = s["gap_speed" if sport == "run" else "speed"].to_numpy(dtype=float)
    keep = np.arange(n) >= WARMUP_S
    keep &= ~s["is_slow"].to_numpy(dtype=bool) & ~np.isnan(speed) & ~np.isnan(hr_lag)
    if sport == "bike":
        grade = s["grade"].to_numpy(dtype=float)
        keep &= np.abs(grade) <= BIKE_MAX_ABS_GRADE  # NaN grade fails
        keep &= speed >= BIKE_MIN_SPEED
        keep &= ~near_stop(t, s["is_slow"].to_numpy(dtype=bool), BIKE_STOP_MARGIN_S)
    return pd.DataFrame(
        {"t": t[keep], "speed": speed[keep], "hr": hr_lag[keep]}, columns=list(EF_SAMPLE_COLUMNS)
    )


def efficiency(prep: Preprocessed, *, sport: str, lthr: float | None) -> EfficiencyResult:
    """METRICS §5.2–§5.4: steady state, EF and decoupling of one activity (`lthr` of the activity's sport,
    valid at its date; None → not steady)."""
    _check_sport(sport)
    steady = is_steady_state(prep, lthr)
    samples = ef_samples(prep, sport=sport)
    n = len(samples)
    if not steady or n == 0:
        return EfficiencyResult(steady, None, None, None, n)
    speed = samples["speed"].to_numpy()
    hr = samples["hr"].to_numpy()
    ef = _ef(speed, hr)
    decoupling = None
    if n >= MIN_DECOUPLING_SAMPLES:
        half = n // 2
        ef1 = _ef(speed[:half], hr[:half])
        ef2 = _ef(speed[half:], hr[half:])
        if ef1 is not None and ef2 is not None and ef1 != 0:
            decoupling = (ef1 - ef2) / ef1 * 100.0
    return EfficiencyResult(steady, ef, decoupling, decoupling_band(decoupling), n)


def decoupling_band(pct: float | None) -> str | None:
    """METRICS §5.3 bands: `< 5` good, `[5, 10]` moderate, `> 10` poor; None → None."""
    if pct is None:
        return None
    good_below, poor_above = DECOUPLING_BANDS
    if pct < good_below:
        return "good"
    return "moderate" if pct <= poor_above else "poor"


def ef_trend(points: pd.DataFrame, days: Sequence[date]) -> pd.Series:
    """METRICS §5.2 trend: for each day d, the median EF of the steady-state activities with `local_date`
    in [d − 27, d]; NaN if none.

    `points` has columns `local_date` (date or datetime64), `ef`, `steady_state`. The result is indexed by
    `days` (in the given order).
    """
    index = pd.Index(list(days), dtype=object)
    if len(index) == 0:
        return pd.Series(np.array([], dtype=float), index=index, name="ef_trend")
    steady = points["steady_state"].fillna(False).astype(bool).to_numpy()
    ef = pd.to_numeric(points["ef"], errors="coerce").to_numpy(dtype=float)
    ok = steady & ~np.isnan(ef)
    point_days = pd.to_datetime(pd.Series(points["local_date"])).dt.normalize().to_numpy()[ok]
    values = ef[ok]
    order = np.argsort(point_days, kind="stable")
    point_days, values = point_days[order], values[order]
    ends = pd.to_datetime(pd.Series(list(days))).dt.normalize().to_numpy()
    starts = ends - np.timedelta64(TREND_WINDOW_DAYS - 1, "D")
    lo = np.searchsorted(point_days, starts, side="left")
    hi = np.searchsorted(point_days, ends, side="right")
    out = np.array([np.median(values[a:b]) if b > a else np.nan for a, b in zip(lo, hi, strict=True)])
    return pd.Series(out, index=index, name="ef_trend", dtype=float)


def near_stop(t: np.ndarray, is_slow: np.ndarray, margin_s: int = BIKE_STOP_MARGIN_S) -> np.ndarray:
    """METRICS §5.4 clarified: True for every kept sample within `margin_s` seconds (inclusive, by `t`) of a
    stop – a slow sample or a missing second between two consecutive kept samples (a pause)."""
    t = np.asarray(t, dtype=np.int64)
    n = len(t)
    if n == 0:
        return np.zeros(0, dtype=bool)
    t0 = int(t[0])
    grid = np.zeros(int(t[-1]) - t0 + 1, dtype=np.int64)  # 1 = stop instant, on the second grid t0..t_end
    grid[:] = 1
    grid[t - t0] = 0  # kept seconds are not stops …
    grid[(t - t0)[np.asarray(is_slow, dtype=bool)]] = 1  # … unless slow
    # Dilate by ± margin_s with a prefix sum: any stop in [t − margin, t + margin].
    csum = np.concatenate(([0], np.cumsum(grid)))
    pos = t - t0
    lo = np.clip(pos - margin_s, 0, len(grid))
    hi = np.clip(pos + margin_s + 1, 0, len(grid))
    return (csum[hi] - csum[lo]) > 0


def _ef(speed: np.ndarray, hr: np.ndarray) -> float | None:
    """`mean(speed) · 60 / mean(hr)` (m/min per bpm); None for an empty set or a zero mean HR."""
    if len(speed) == 0:
        return None
    mean_hr = float(np.mean(hr))
    return float(np.mean(speed)) * 60.0 / mean_hr if mean_hr > 0 else None


def _block_means(hr: np.ndarray) -> np.ndarray:
    """Means of consecutive 60-sample blocks (last partial block dropped), skipping blocks with < 30 valid
    HR values; NaN values are ignored within a block."""
    n_blocks = len(hr) // BLOCK_S
    blocks = hr[: n_blocks * BLOCK_S].reshape(n_blocks, BLOCK_S)
    n_valid = np.count_nonzero(~np.isnan(blocks), axis=1)
    ok = n_valid >= BLOCK_MIN_VALID
    sums = np.nansum(blocks[ok], axis=1)
    return sums / n_valid[ok]


def _longest_run(mask: np.ndarray) -> int:
    """Length of the longest run of consecutive True values."""
    if not mask.any():
        return 0
    padded = np.concatenate(([False], mask, [False])).astype(np.int8)
    edges = np.flatnonzero(np.diff(padded))
    return int(np.max(edges[1::2] - edges[::2]))


def _check_sport(sport: str) -> None:
    if sport not in SPORTS:
        raise ValueError(f"sport must be one of {SPORTS}, got {sport!r}")
