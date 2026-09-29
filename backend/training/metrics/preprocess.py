"""Stream preprocessing – METRICS §0 (phase 2).

Input: `activity_stream` rows (`t, hr, speed, alt, cadence, lat, lon, distance, moving, grade, gap_speed`)
as written by `normalize/streams.py`. Those already have §0.1 (1 s grid, forward-fill ≤ 10 s), the §0.2
`moving` flag and the §0.4 speed derivation from distance; everything else happens here:

# METRICS §0.2
Keep only samples where the timer is running (drop paused/stopped time). `moving_s` = number of kept samples.

# METRICS §0.3
HR validity: `40 ≤ hr ≤ 230`, else NaN. `hr_coverage` = valid HR samples / kept samples.
If `hr_coverage < 0.70`, all HR-based metrics for the activity are flagged `low_confidence=True`.
(Clarified: applied to the kept samples after the §0.1 forward-fill; no kept sample → `hr_coverage = 0`.)

# METRICS §0.4
Clamp run speed to `0–7 m/s`, bike to `0–25 m/s`. Walking/stopped samples (run `< 1.0 m/s`, bike
`< 2.0 m/s`) are kept for load metrics but excluded from efficiency/curve metrics.
(Clarified: values below 0 → 0, above the maximum → the maximum, not dropped; `other` uses the run limits.)

# METRICS §0.5
Altitude: 5 s rolling median. Grade over a 10 s centred window: `grade = Δalt / Δdist`, clamp to ±0.30,
NaN where `Δdist < 5 m`.
(Clarified: both windows centred, on the kept samples in time order – a pause is skipped, not bridged by
NaN. Rolling median: 5 samples, at least 3 non-NaN. Grade at i uses samples i−5 and i+5 clipped at the
ends: `Δalt = alt[i+5] − alt[i−5]` (smoothed), `Δdist = dist[i+5] − dist[i−5]` (cumulative). NaN if either
value is missing or `Δdist < 5 m`.)

# METRICS §0.6
For any pairing of HR with pace/speed at sample level (§5, §6), shift HR **back** by 30 s → `lag_hr`.

Pure functions, no I/O.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from training.metrics.gap import gap_speed as _gap_speed

SPORTS = ("run", "bike", "other")
SAMPLE_COLUMNS: tuple[str, ...] = ("t", "hr", "speed", "alt", "grade", "distance", "gap_speed", "is_slow")
REQUIRED_COLUMNS: tuple[str, ...] = ("t", "hr", "speed", "alt", "distance", "moving")

HR_MIN, HR_MAX = 40.0, 230.0  # §0.3, inclusive
LOW_CONFIDENCE_COVERAGE = 0.70  # §0.3
MAX_SPEED = {"run": 7.0, "bike": 25.0, "other": 7.0}  # §0.4, m/s
SLOW_SPEED = {"run": 1.0, "bike": 2.0, "other": 1.0}  # §0.4, m/s (walking/stopped below)
ALT_MEDIAN_WINDOW, ALT_MEDIAN_MIN = 5, 3  # §0.5
GRADE_HALF_WINDOW = 5  # §0.5: samples i−5 .. i+5
GRADE_MIN_DIST_M = 5.0  # §0.5
GRADE_CLAMP = 0.30  # §0.5
HR_LAG_S = 30  # §0.6


@dataclass(frozen=True)
class Preprocessed:
    """Kept samples of one activity (METRICS §0.2) and the per-activity §0 figures.

    `samples`: columns `SAMPLE_COLUMNS`, time order, index 0..moving_s−1. `hr` is valid or NaN (§0.3),
    `speed` clamped (§0.4), `alt` smoothed and `grade` per §0.5, `distance` cumulative as given,
    `gap_speed` per §3 for runs (= speed for bike/other), `is_slow` = walking/stopped (§0.4; NaN speed is
    not slow).
    """

    samples: pd.DataFrame
    moving_s: int
    hr_coverage: float
    low_confidence: bool


def preprocess(streams: pd.DataFrame, sport: str) -> Preprocessed:
    """METRICS §0.2–§0.5 (+ §3 GAP for runs) on one activity's 1 Hz `activity_stream` rows.

    `sport` is "run", "bike" or "other". Rows need not be sorted. NULLs from the DB (None / object
    columns) are read as NaN; a NULL `moving` counts as running (the §0.2 "unknown → running" rule).
    """
    if sport not in SPORTS:
        raise ValueError(f"sport must be one of {SPORTS}, got {sport!r}")
    missing = [c for c in REQUIRED_COLUMNS if c not in streams.columns]
    if missing:
        raise ValueError(f"streams lack column(s) {missing}")

    ordered = streams.sort_values("t", kind="stable")
    moving = ordered["moving"]
    running = moving.where(moving.notna(), True).astype(bool).to_numpy()
    kept = ordered.loc[running]

    t = np.asarray(pd.to_numeric(kept["t"]), dtype=np.int64)
    hr = _floats(kept["hr"])
    speed = _floats(kept["speed"])
    alt = _floats(kept["alt"])
    distance = _floats(kept["distance"])

    # §0.3 HR validity and coverage over the kept samples.
    hr[~((hr >= HR_MIN) & (hr <= HR_MAX))] = np.nan
    moving_s = len(t)
    hr_coverage = float(np.count_nonzero(~np.isnan(hr)) / moving_s) if moving_s else 0.0

    # §0.4 clamp (NaN stays NaN) and the walking/stopped flag.
    speed = np.clip(speed, 0.0, MAX_SPEED[sport])
    is_slow = speed < SLOW_SPEED[sport]  # NaN compares False

    # §0.5 altitude median and grade, over kept samples in time order.
    alt_smooth = smooth_altitude(alt)
    grade = grade_from(alt_smooth, distance)

    # §3 GAP – runs only.
    gap = _gap_speed(speed, grade) if sport == "run" else speed.copy()

    samples = pd.DataFrame(
        {
            "t": t,
            "hr": hr,
            "speed": speed,
            "alt": alt_smooth,
            "grade": grade,
            "distance": distance,
            "gap_speed": gap,
            "is_slow": is_slow.astype(bool),
        },
        columns=list(SAMPLE_COLUMNS),
    )
    return Preprocessed(
        samples=samples,
        moving_s=moving_s,
        hr_coverage=hr_coverage,
        low_confidence=hr_coverage < LOW_CONFIDENCE_COVERAGE,
    )


def smooth_altitude(alt: np.ndarray) -> np.ndarray:
    """METRICS §0.5: centred 5-sample rolling median, NaN unless ≥ 3 of the 5 values are present."""
    series = pd.Series(np.asarray(alt, dtype=float))
    smoothed = series.rolling(ALT_MEDIAN_WINDOW, center=True, min_periods=ALT_MEDIAN_MIN).median()
    return smoothed.to_numpy(dtype=float)


def grade_from(alt_smooth: np.ndarray, distance: np.ndarray) -> np.ndarray:
    """METRICS §0.5: `grade[i] = (alt[i+5] − alt[i−5]) / (dist[i+5] − dist[i−5])`, indices clipped at the
    ends, clamped to ±0.30; NaN where a value is missing or `Δdist < 5 m`."""
    alt_smooth = np.asarray(alt_smooth, dtype=float)
    distance = np.asarray(distance, dtype=float)
    n = len(alt_smooth)
    grade = np.full(n, np.nan)
    if n == 0:
        return grade
    i = np.arange(n)
    lo = np.clip(i - GRADE_HALF_WINDOW, 0, n - 1)
    hi = np.clip(i + GRADE_HALF_WINDOW, 0, n - 1)
    d_alt = alt_smooth[hi] - alt_smooth[lo]
    d_dist = distance[hi] - distance[lo]
    ok = ~np.isnan(d_alt) & ~np.isnan(d_dist) & (d_dist >= GRADE_MIN_DIST_M)
    grade[ok] = np.clip(d_alt[ok] / d_dist[ok], -GRADE_CLAMP, GRADE_CLAMP)
    return grade


def lag_hr(hr: np.ndarray, lag_s: int = HR_LAG_S) -> np.ndarray:
    """METRICS §0.6 helper for phase 4: `result[i] = hr[i + lag_s]`, NaN where `i + lag_s` is outside.

    This pairs speed(t) with HR(t + 30 s), i.e. HR is moved back by 30 s to line up with the pace that
    caused it. The direction is still an open question (docs/STATUS.md → Known issues, "§0.6 HR-lag
    direction"); a negative `lag_s` gives the other direction (`result[i] = hr[i − |lag_s|]`). The
    array is shifted by position, so call it on a gap-free series (e.g. the kept samples of one
    continuous stretch) when positions must equal seconds.
    """
    hr = np.asarray(hr, dtype=float)
    n = len(hr)
    out = np.full(n, np.nan)
    if abs(lag_s) >= n:
        return out
    if lag_s >= 0:
        out[: n - lag_s] = hr[lag_s:]
    else:
        out[-lag_s:] = hr[: n + lag_s]
    return out


def _floats(column: pd.Series) -> np.ndarray:
    """A stream column as float64; None / non-numeric → NaN (DB rows can arrive as object dtype)."""
    return np.array(pd.to_numeric(column, errors="coerce"), dtype=float)
