"""Generators for synthetic 1 Hz streams with known metric values (METRICS §0–§3, phase 2).

Every generator returns a DataFrame shaped like the `activity_stream` rows produced by
`training.normalize.streams.normalize_streams`:

- exactly `STREAM_COLUMNS` (`t, hr, speed, alt, cadence, lat, lon, distance, moving, grade, gap_speed`);
- `t` int64 = 0..n−1, `moving` bool (timer running), everything else float64 with NaN = no value;
- `grade` and `gap_speed` all NaN (they are computed by `metrics/preprocess.py`).

Cumulative distance matches the speed: `distance[0] = 0` and every running second adds `speed[i] · 1 s`
(paused seconds and NaN speed add nothing). This is the §0.4 convention, where the speed of second b is
`(d_b − d_a) / (t_b − t_a)`.

Each docstring states the expected metric values from docs/METRICS.md. `lthr` / `threshold_speed` there
are whatever the test passes.
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd

from training.normalize.streams import STREAM_COLUMNS

Values = float | int | bool | np.ndarray | Sequence[float] | Sequence[bool]


def stream(
    *,
    hr: Values = np.nan,
    speed: Values = np.nan,
    alt: Values = 100.0,
    moving: Values = True,
    distance: Values | None = None,
    cadence: Values = np.nan,
    lat: Values = np.nan,
    lon: Values = np.nan,
    n: int | None = None,
) -> pd.DataFrame:
    """Build a stream frame from scalars (broadcast) and/or equally long arrays.

    `n` defaults to the length of the array arguments. `distance=None` derives the cumulative distance
    from `speed` and `moving` (see the module docstring). Pass an explicit array or `np.nan` to override
    it.
    """
    given = {"hr": hr, "speed": speed, "alt": alt, "moving": moving, "cadence": cadence, "lat": lat}
    given["lon"] = lon
    if distance is not None:
        given["distance"] = distance
    lengths = {len(np.atleast_1d(v)) for v in given.values() if np.ndim(v) > 0}
    if n is None:
        if len(lengths) != 1:
            raise ValueError(f"cannot infer n from array lengths {sorted(lengths)}")
        n = lengths.pop()
    elif lengths - {n}:
        raise ValueError(f"array lengths {sorted(lengths)} do not match n = {n}")

    def full(value: Values, dtype: type) -> np.ndarray:
        return np.broadcast_to(np.asarray(value, dtype=dtype), (n,)).copy()

    cols: dict[str, np.ndarray] = {
        "t": np.arange(n, dtype=np.int64),
        "hr": full(hr, float),
        "speed": full(speed, float),
        "alt": full(alt, float),
        "cadence": full(cadence, float),
        "lat": full(lat, float),
        "lon": full(lon, float),
        "moving": full(moving, bool),
        "grade": np.full(n, np.nan),
        "gap_speed": np.full(n, np.nan),
    }
    cols["distance"] = (
        cumulative_distance(cols["speed"], cols["moving"]) if distance is None else full(distance, float)
    )
    return pd.DataFrame({c: cols[c] for c in STREAM_COLUMNS}, columns=STREAM_COLUMNS)


def cumulative_distance(speed: np.ndarray, moving: np.ndarray) -> np.ndarray:
    """d[0] = 0, d[i] = d[i−1] + speed[i] for running seconds with a speed, else d[i−1]."""
    steps = np.where(np.asarray(moving, dtype=bool) & ~np.isnan(speed), speed, 0.0)
    if len(steps):
        steps[0] = 0.0
    return np.cumsum(steps)


def constant(n: int = 3600, *, hr: float = 150.0, speed: float = 3.0, alt: float = 100.0) -> pd.DataFrame:
    """`n` s at a constant HR and speed on flat ground, timer running throughout.

    Expected, with `lthr == hr` and (runs) `threshold_speed == speed`:
    - §0: moving_s = n, hr_coverage = 1.0 (for 40 ≤ hr ≤ 230), low_confidence False. Grade is 0.0 wherever
      Δdist ≥ 5 m, i.e. everywhere for speed ≥ 1 m/s (the clipped end windows span 5 s). gap_speed == speed.
    - §2.1: IF = 1.0 per sample, hrTSS = n / 36 (100.0 for n = 3600), IF_hr = 1.0.
      With `hr = 0.83 · lthr` (e.g. 166 at lthr 200): IF = 0.75, hrTSS = 0.5625 · n / 36 (56.25 for 3600 s).
    - §2.2: TRIMP_norm = 100 · n / 3600 when hr == lthr.
    - §2.3: NGS = speed, IF_pace = 1.0, rTSS = n / 36 (100.0 for n = 3600); None for n < 59 (fewer than
      30 full 30-sample windows).
    - §1: time_in_zone = {"4": n, others 0} for HR (r = 1.0) and pace (s = 1.0).
    """
    return stream(hr=hr, speed=speed, alt=alt, n=n)


def hr_ramp(hr_start: int = 100, hr_end: int = 219, *, speed: float = 3.0) -> pd.DataFrame:
    """HR rising by 1 bpm per second from `hr_start` to `hr_end` (both inclusive), flat, constant speed.

    Expected with lthr = 200 (§1 bounds at 136 / 168 / 190 / 210 bpm) and the defaults (100..219, 120 s):
    time_in_hr_zone = {"1": 36, "2": 32, "3": 22, "4": 21, "5": 9} – 100..135 Z1, 136..167 Z2,
    168..189 Z3, 190..210 Z4 (1.05 is inside Z4), 211..219 Z5.
    """
    hr = np.arange(hr_start, hr_end + 1, dtype=float)
    return stream(hr=hr, speed=speed)


def intervals(
    reps: int = 6,
    work_s: int = 300,
    rest_s: int = 300,
    *,
    hr_work: float = 210.0,
    hr_rest: float = 166.0,
    speed_work: float = 4.0,
    speed_rest: float = 2.0,
) -> pd.DataFrame:
    """`reps` × (`work_s` at hr_work / speed_work, then `rest_s` at hr_rest / speed_rest), flat.

    Expected with lthr = 200 and the defaults (r = 1.05 → IF 1.05 and r = 0.83 → IF 0.75, 3600 s):
    - §2.1: hrTSS = (1800 · 1.05² + 1800 · 0.75²) / 36 = (1984.5 + 1012.5) / 36 = 83.25,
      IF_hr = sqrt(83.25 · 36 / 3600) = sqrt(0.8325).
    - §1: time_in_hr_zone = {"1": 0, "2": 1800, "3": 0, "4": 1800, "5": 0} (0.83 → Z2, 1.05 → Z4).
    - §2.3: NGS > mean speed (3.0 m/s): the 4th-power mean weights the fast blocks.
    """
    block_hr = np.r_[np.full(work_s, hr_work), np.full(rest_s, hr_rest)]
    block_speed = np.r_[np.full(work_s, speed_work), np.full(rest_s, speed_rest)]
    return stream(hr=np.tile(block_hr, reps), speed=np.tile(block_speed, reps))


def hilly(
    n: int = 600, *, speed: float = 2.5, grade: float = 0.10, alt0: float = 100.0, hr: float = 150.0
) -> pd.DataFrame:
    """A constant-grade slope: alt = alt0 + grade · distance, distance = speed · t.

    Expected (§0.5, §3):
    - smoothed altitude == alt for samples 2..n−3 (a 5-sample median of a linear profile is the centre);
      at the ends the shortened windows shift it (sample 0 → alt[1], sample 1 → alt at t = 1.5);
    - grade == `grade` clamped to ±0.30 for samples 7..n−8. The first/last 7 samples are pulled towards 0
      by the shifted end altitudes (sample 0: 0.8 · grade, sample 5: 0.9 · grade, sample 6: 0.95 · grade);
    - runs: gap_speed = speed · C(grade) / 3.6 on those samples. 2.5 m/s at +10 % gives
      2.5 · 5.968214 / 3.6 = 4.144593 m/s; at −10 %, 2.5 · 2.151706 / 3.6 = 1.494240 m/s.
    """
    t = np.arange(n, dtype=float)
    distance = speed * t
    return stream(hr=hr, speed=speed, alt=alt0 + grade * distance, distance=distance)


def with_pause(
    df: pd.DataFrame,
    start: int,
    length: int,
    *,
    hr: float | None = None,
    speed: float = 0.0,
    alt: float | None = None,
) -> pd.DataFrame:
    """Copy of `df` with the timer stopped for t in [start, start + length).

    During the pause `moving` is False, speed is `speed` (default 0) and HR / altitude are replaced when
    given. Distance is re-derived (paused seconds add nothing) unless `df` has no distance at all.

    Expected (§0.2): moving_s = len(df) − length, and the paused rows are dropped before anything else, so
    every metric equals that of the stream without them, whatever HR or altitude the pause has. For
    example `with_pause(constant(4200, hr=lthr), 1800, 600, hr=200)` has moving_s = 3600 and hrTSS = 100.0.
    """
    out = df.copy()
    paused = (out["t"] >= start) & (out["t"] < start + length)
    out.loc[paused, "moving"] = False
    out.loc[paused, "speed"] = speed
    if hr is not None:
        out.loc[paused, "hr"] = hr
    if alt is not None:
        out.loc[paused, "alt"] = alt
    if out["distance"].notna().any():
        out["distance"] = cumulative_distance(out["speed"].to_numpy(), out["moving"].to_numpy())
    return out


def with_hr_dropout(df: pd.DataFrame, start: int, length: int) -> pd.DataFrame:
    """Copy of `df` with HR NaN for t in [start, start + length) – a strap dropout longer than the 10 s
    forward-fill of §0.1.

    Expected (running timer, HR at lthr elsewhere): hr_coverage = 1 − length / moving_s (§0.3);
    hrTSS = (moving_s − length) / 36 because NaN samples contribute 0 (§2.1); IF_hr =
    sqrt((moving_s − length) / moving_s), because moving_s still counts the dropout.
    """
    out = df.copy()
    out.loc[(out["t"] >= start) & (out["t"] < start + length), "hr"] = np.nan
    return out


def without_gps(df: pd.DataFrame) -> pd.DataFrame:
    """Copy of `df` without distance / lat / lon (GPS off, e.g. a treadmill run without distance).

    Expected (§2.3): usable_gps is False, so rTSS / IF_pace are None and a run's primary load falls back to
    hrTSS (§2.4). Grade is NaN everywhere (§0.5), so gap_speed == speed (§3).
    """
    out = df.copy()
    out[["distance", "lat", "lon"]] = np.nan
    return out


# ---------------------------------------------------------------- phase 4 (METRICS §5, §6.1)


def with_segment(
    df: pd.DataFrame,
    start: int,
    length: int,
    *,
    hr: float | None = None,
    speed: float | None = None,
) -> pd.DataFrame:
    """Copy of `df` with HR and/or speed replaced for t in [start, start + length); the timer keeps running.

    Distance is re-derived from the new speed (unless `df` has no distance at all). A warm-up is
    `with_segment(df, 0, 600, hr=120.0, speed=2.0)`: §5.1/§5.2/§6.1 drop the first 600 s, so it changes
    nothing there – except the lagged HR partners of samples 570..599 (§0.6), which are dropped anyway.
    """
    out = df.copy()
    seg = (out["t"] >= start) & (out["t"] < start + length)
    if hr is not None:
        out.loc[seg, "hr"] = hr
    if speed is not None:
        out.loc[seg, "speed"] = speed
    if out["distance"].notna().any():
        out["distance"] = cumulative_distance(out["speed"].to_numpy(), out["moving"].to_numpy())
    return out


def block_hr(
    n: int = 2400,
    *,
    base: float = 150.0,
    amplitude: float = 6.0,
    start: int = 600,
    block: int = 60,
    speed: float = 3.0,
) -> pd.DataFrame:
    """Flat, constant speed; HR = base for t < start, then `base + amplitude` / `base − amplitude`
    alternating per `block`-second block (block 0 = [start, start + block) is the high one).

    Expected (§5.1, the defaults): 30 blocks of 60 s after the first 600 s, 15 high and 15 low, so the
    mean HR is `base` and the population std of the 60 s means is exactly `amplitude` (the sample std
    would be `amplitude · sqrt(30/29)`).
    """
    t = np.arange(n)
    sign = np.where(((t - start) // block) % 2 == 0, 1.0, -1.0)
    hr = np.where(t < start, base, base + amplitude * sign)
    return stream(hr=hr, speed=speed)


def hr_drift(
    n: int = 3630, *, hr0: float = 150.0, slope: float = 0.0025, drift_from: int = 630, speed: float = 3.0
) -> pd.DataFrame:
    """Flat, constant speed; HR = hr0 for t < drift_from, then `hr0 + slope · (t − drift_from)`.

    Expected with the defaults (§0.6, §5.3, run): the EF sample set is positions 600..3599 (m = 3000) and its
    lagged HR is `hr[i + 30] = 150 + 0.0025 · (i − 600)`, i.e. 150 → 157.4975. Half means 150 + 0.0025 ·
    749.5 = 151.87375 and 150 + 0.0025 · 2249.5 = 155.62375, so with a constant speed
    `decoupling_pct = (1 − 151.87375 / 155.62375) · 100 = 375 / 155.62375 ≈ 2.40966` ("good").
    """
    t = np.arange(n, dtype=float)
    hr = np.where(t < drift_from, hr0, hr0 + slope * (t - drift_from))
    return stream(hr=hr, speed=speed)


def speed_hr_step(
    n: int = 2430,
    *,
    step_at: int = 1200,
    hr_delay: int = 30,
    speed0: float = 3.0,
    speed1: float = 3.1,
    hr0: float = 150.0,
    hr1: float = 155.0,
) -> pd.DataFrame:
    """Flat; speed steps speed0 → speed1 at `step_at`, HR steps hr0 → hr1 `hr_delay` seconds later.

    Expected (§0.6 with the defaults): HR responds 30 s late, so every lagged pair (speed[t], hr[t + 30])
    is (3.0, 150) or (3.1, 155) – a constant ratio of 0.02 (m/s)/bpm, hence EF = 0.02 · 60 = 1.2 exactly
    in both halves and decoupling 0. With the opposite lag direction 60 pairs would be (3.1, 150)/(3.0, 155).
    """
    t = np.arange(n)
    return stream(hr=np.where(t < step_at + hr_delay, hr0, hr1), speed=np.where(t < step_at, speed0, speed1))


def flat_then_climb(
    n: int = 2430, *, climb_from: int = 1500, grade: float = 0.02, speed: float = 8.0, hr: float = 140.0
) -> pd.DataFrame:
    """Constant speed and HR; flat (alt 100) up to `climb_from`, then climbing at `grade`.

    Expected (§0.5): altitude is non-decreasing, so the 5-sample median is the altitude itself away from the
    ends and `grade[i] = grade · (i + 5 − climb_from) / 10` for climb_from − 5 ≤ i ≤ climb_from + 5 (0 before,
    `grade` after). With grade 0.02 the §5.4 filter `|grade| ≤ 0.01` keeps exactly the samples i ≤ climb_from
    (i = climb_from has grade 0.01 up to rounding just below it).
    """
    t = np.arange(n, dtype=float)
    distance = speed * t
    alt = 100.0 + grade * np.maximum(0.0, distance - speed * climb_from)
    return stream(hr=hr, speed=speed, alt=alt, distance=distance)


def ramp(
    n: int = 930,
    *,
    hr0: float = 100.0,
    hr_slope: float = 0.01,
    speed0: float = 2.0,
    speed_slope: float = 0.001,
) -> pd.DataFrame:
    """Flat; `hr = hr0 + hr_slope · t`, `speed = speed0 + speed_slope · t` (both linear in t).

    Expected (§6.1, run, the defaults): the aggregate sample set is positions 600..899 (the last 30 have no
    lagged partner), i.e. five 60 s blocks starting at 600 + 60k. Block k has mean gap_speed
    `2.0 + 0.001 · (629.5 + 60k)` and mean lagged HR `100 + 0.01 · (659.5 + 60k)` (partner t + 30).
    """
    t = np.arange(n, dtype=float)
    return stream(hr=hr0 + hr_slope * t, speed=speed0 + speed_slope * t)
