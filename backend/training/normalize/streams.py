"""activityDetailMetrics → 1 Hz `activity_stream` rows, mapped by metric descriptor key (phase 1).

Input: `Garmin.get_activity_details(id)`. Each `activityDetailMetrics[].metrics` list is positional; the
position → channel mapping comes from `metricDescriptors[].{key, metricsIndex}` and differs per device
and activity type, so channels are looked up by key only, never by position.

Preprocessing follows METRICS §0 as far as it belongs to ingestion:

- §0.1 resample to a 1 s grid `t = 0..T` (integer seconds since the first sample; several samples in
  one second → the last one wins). Per channel, a gap is the time between two consecutive valid values
  a → b; if `b − a ≤ 10 s` the seconds in between are forward-filled from a, otherwise they all stay NaN.
  This covers both missing samples and null values inside a channel (HR strap dropout, GPS loss).
  Leading and trailing NaN runs stay NaN.
- §0.2 `moving` = timer running, from the timer channel `sumDuration`: between samples a → b
  (spacing g, timer increase Δ) the last round(min(Δ, g)) grid seconds of (a, b] are running – so the
  resume sample b itself is running – and the rest paused; the first sample is running. Without a timer
  channel everything is running.
- §0.4 (derivation only) speed from the Garmin speed channel; if it is absent or all null, from
  Δ cumulative distance / Δt between consecutive valid distance values, spread over the grid seconds
  (a, b] – NaN over the whole of (a, b] when `b − a > 10 s`. Clamping is phase 2.

Values are raw: no HR validity filter, speed clamping, smoothing, grade or GAP (phase 2,
`metrics/preprocess.py`). `grade` and `gap_speed` are all NaN here. `distance` (cumulative metres) is
kept for the phase-2 grade calculation. Pure functions, no I/O.
"""

import logging
import math
from collections.abc import Mapping, Sequence
from itertools import pairwise
from typing import Any

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

STREAM_COLUMNS = [
    "t",
    "hr",
    "speed",
    "alt",
    "cadence",
    "lat",
    "lon",
    "distance",
    "moving",
    "grade",
    "gap_speed",
]

MAX_FFILL_GAP_S = 10  # METRICS §0.1
MAX_SPAN_S = 3 * 24 * 3600  # sanity cap on the grid length (longer than any single activity)

# Candidate descriptor keys per output column, in order of preference.
CHANNEL_KEYS: dict[str, tuple[str, ...]] = {
    "hr": ("directHeartRate",),
    "speed": ("directSpeed",),
    "alt": ("directElevation",),
    "cadence": ("directRunCadence", "directBikeCadence"),
    "lat": ("directLatitude",),
    "lon": ("directLongitude",),
    "distance": ("sumDistance",),
}
TIMER_KEYS = ("sumDuration",)
TIMESTAMP_KEY = "directTimestamp"  # epoch milliseconds, GMT
ELAPSED_KEYS = ("sumElapsedDuration",)  # fallback clock (seconds since start) if there is no timestamp


def empty_streams() -> pd.DataFrame:
    """An empty stream frame with `STREAM_COLUMNS` and their dtypes."""
    return _frame(np.zeros(0, dtype=np.int64), {}, np.zeros(0, dtype=bool))


def normalize_streams(details: dict) -> pd.DataFrame:
    """Garmin activity details → 1 Hz DataFrame with exactly `STREAM_COLUMNS` (METRICS §0.1, §0.2, §0.4).

    `t` is int64 seconds since the first sample, `moving` bool, everything else float64 (NaN = no value).
    Empty or unusable details give an empty frame with the same columns.
    """
    details = details if isinstance(details, Mapping) else {}
    key_to_index = descriptor_index(details.get("metricDescriptors"))
    samples = [
        s.get("metrics") if isinstance(s, Mapping) else None
        for s in details.get("activityDetailMetrics") or []
    ]
    samples = [m if isinstance(m, Sequence) and not isinstance(m, str) else [] for m in samples]
    if not samples or not key_to_index:
        return empty_streams()

    def channel(keys: Sequence[str]) -> np.ndarray | None:
        return _pick_channel(samples, key_to_index, keys)

    clock_s = _clock_seconds(samples, key_to_index)
    if clock_s is None:
        log.warning("activity details have no %s / elapsed-duration channel; no streams", TIMESTAMP_KEY)
        return empty_streams()

    raw = {col: channel(keys) for col, keys in CHANNEL_KEYS.items()}
    timer = channel(TIMER_KEYS)

    # Drop samples without a time, order by time (stable), bucket into whole seconds, last one wins.
    valid = ~np.isnan(clock_s)
    if not valid.any():
        return empty_streams()
    order = np.flatnonzero(valid)[np.argsort(clock_s[valid], kind="stable")]
    rel = clock_s[order] - clock_s[order[0]]
    if rel[-1] > MAX_SPAN_S:  # a corrupt timestamp must not allocate a gigantic grid
        log.warning("activity details span %.0f s; samples after %d s dropped", rel[-1], MAX_SPAN_S)
        order, rel = order[rel <= MAX_SPAN_S], rel[rel <= MAX_SPAN_S]
    sec_all = np.floor(rel + 1e-6).astype(np.int64)
    keep_last = np.append(sec_all[1:] != sec_all[:-1], True)
    idx = order[keep_last]
    sec = sec_all[keep_last]

    n = int(sec[-1]) + 1
    grid = np.arange(n, dtype=np.int64)
    spacing = np.diff(sec)

    columns: dict[str, np.ndarray] = {}
    placed: dict[str, np.ndarray] = {}
    for col, values in raw.items():
        on_grid = np.full(n, np.nan)
        if values is not None:
            on_grid[sec] = values[idx]
        placed[col] = on_grid
        columns[col] = _ffill_bounded(on_grid, MAX_FFILL_GAP_S)

    if raw["speed"] is None or np.isnan(raw["speed"]).all():
        columns["speed"] = _speed_from_distance(placed["distance"], MAX_FFILL_GAP_S)

    moving = _moving(timer[idx] if timer is not None else None, sec, grid, spacing)
    return _frame(grid, columns, moving)


def _ffill_bounded(values: np.ndarray, max_gap_s: int) -> np.ndarray:
    """METRICS §0.1: forward-fill NaN runs whose bounding valid values are ≤ `max_gap_s` apart."""
    n = len(values)
    valid = ~np.isnan(values)
    if n == 0 or valid.all() or not valid.any():
        return values.copy()
    pos = np.arange(n)
    prev_valid = np.maximum.accumulate(np.where(valid, pos, -1))
    next_valid = np.minimum.accumulate(np.where(valid, pos, n)[::-1])[::-1]
    fill = ~valid & (prev_valid >= 0) & (next_valid < n) & (next_valid - prev_valid <= max_gap_s)
    out = values.copy()
    out[fill] = values[prev_valid[fill]]
    return out


def descriptor_index(descriptors: Any) -> dict[str, int]:
    """`metricDescriptors[]` → {key: metricsIndex}; entries without a str key / non-negative int index are
    skipped, the first descriptor of a duplicated key wins."""
    out: dict[str, int] = {}
    for d in descriptors if isinstance(descriptors, list) else []:
        if not isinstance(d, Mapping):
            continue
        key, index = d.get("key"), d.get("metricsIndex")
        if isinstance(key, str) and isinstance(index, int) and not isinstance(index, bool) and index >= 0:
            out.setdefault(key, index)
    return out


def _column(samples: Sequence[Sequence[Any]], index: int) -> np.ndarray:
    """One positional channel as float64; missing entries and non-numeric values become NaN."""
    return np.array([_num(m[index]) if index < len(m) else math.nan for m in samples], dtype=float)


def _pick_channel(
    samples: Sequence[Sequence[Any]], key_to_index: Mapping[str, int], keys: Sequence[str]
) -> np.ndarray | None:
    """First candidate key with any value; else the first one present (all NaN); else None."""
    present = [_column(samples, key_to_index[k]) for k in keys if k in key_to_index]
    for values in present:
        if not np.isnan(values).all():
            return values
    return present[0] if present else None


def _clock_seconds(samples: Sequence[Sequence[Any]], key_to_index: Mapping[str, int]) -> np.ndarray | None:
    """Sample time in seconds: `directTimestamp` (ms), else `sumElapsedDuration` (s)."""
    if TIMESTAMP_KEY in key_to_index:
        ts = _column(samples, key_to_index[TIMESTAMP_KEY])
        ts[ts <= 0] = np.nan  # epoch 0 / negative = no timestamp
        if not np.isnan(ts).all():
            return ts / 1000.0
    elapsed = _pick_channel(samples, key_to_index, ELAPSED_KEYS)
    if elapsed is not None and not np.isnan(elapsed).all():
        log.info("activity details have no %s; using elapsed duration as the clock", TIMESTAMP_KEY)
        return elapsed
    return None


def _speed_from_distance(distance: np.ndarray, max_gap_s: int) -> np.ndarray:
    """METRICS §0.4 fallback: v = (d_b − d_a) / (t_b − t_a) on the grid seconds (a, b] between consecutive
    valid distance values; the whole of (a, b] is NaN when `t_b − t_a > max_gap_s`; t = 0 is NaN."""
    speed = np.full(len(distance), np.nan)
    pos = np.flatnonzero(~np.isnan(distance))
    if len(pos) < 2:
        return speed
    for a, b in pairwise(pos):
        if b - a <= max_gap_s:
            speed[a + 1 : b + 1] = (distance[b] - distance[a]) / (b - a)
    return speed


def _moving(timer: np.ndarray | None, sec: np.ndarray, grid: np.ndarray, spacing: np.ndarray) -> np.ndarray:
    """METRICS §0.2: timer running per grid second, from the timer increase between original samples.

    In a gap a → b the last round(min(Δtimer, g)) seconds are running, so the resume sample b is running.
    """
    moving = np.ones(len(grid), dtype=bool)
    if timer is None or len(sec) < 2 or np.isnan(timer).all():
        return moving
    delta = timer[1:] - timer[:-1]
    running_s = np.where(
        np.isnan(delta),
        spacing,  # unknown timer → assume running
        np.floor(np.clip(np.minimum(delta, spacing), 0, None) + 0.5),  # round half up
    )
    after = np.searchsorted(sec, grid[1:], side="left")  # sample b closing the gap that contains t
    moving[1:] = (sec[after] - grid[1:]) < running_s[after - 1]
    return moving


def _frame(t: np.ndarray, columns: Mapping[str, np.ndarray], moving: np.ndarray) -> pd.DataFrame:
    n = len(t)
    data: dict[str, Any] = {}
    for col in STREAM_COLUMNS:
        if col == "t":
            data[col] = t.astype(np.int64)
        elif col == "moving":
            data[col] = moving.astype(bool)
        else:
            data[col] = np.asarray(columns.get(col, np.full(n, np.nan)), dtype=float)
    return pd.DataFrame(data, columns=STREAM_COLUMNS)


def _num(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float) or not math.isfinite(value):
        return math.nan
    return float(value)
