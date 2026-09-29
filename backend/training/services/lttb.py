"""Largest-Triangle-Three-Buckets downsampling (Steinarsson 2013) for chart streams. Pure, numpy only.

`lttb_indices` is the classic algorithm on one series. Streams have gaps (HR dropouts, no altitude
indoors), so `select_indices` wraps it: per series it runs LTTB over the valid (finite) samples only and
adds one marker per interior gap so a chart shows a break instead of a line across it, then unions the
picks of all series onto one shared time axis (`StreamsDTO.t` is common to every series).
"""

from collections.abc import Mapping

import numpy as np

MIN_POINTS = 3  # first + last + at least one bucket pick


def lttb_indices(x: np.ndarray, y: np.ndarray, threshold: int) -> np.ndarray:
    """Indices (ascending, unique) of at most `threshold` points that best preserve the shape of `y(x)`.

    The first and last point are always kept. `x` must be ascending, `x` and `y` finite and equally long;
    if `threshold >= len(x)` every index is returned. Raises ValueError for `threshold < 3`.
    """
    if threshold < MIN_POINTS:
        raise ValueError(f"threshold must be at least {MIN_POINTS}, got {threshold}")
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.shape != y.shape or x.ndim != 1:
        raise ValueError("x and y must be one-dimensional and equally long")
    n = len(x)
    if threshold >= n:
        return np.arange(n)

    every = (n - 2) / (threshold - 2)  # bucket width over the n − 2 interior points
    picked = np.empty(threshold, dtype=np.int64)
    picked[0], picked[-1] = 0, n - 1
    anchor = 0
    for i in range(threshold - 2):
        # Average of the next bucket is the third triangle corner (the last bucket uses the final point).
        next_lo = int((i + 1) * every) + 1
        next_hi = min(int((i + 2) * every) + 1, n)
        avg_x, avg_y = x[next_lo:next_hi].mean(), y[next_lo:next_hi].mean()
        lo, hi = int(i * every) + 1, int((i + 1) * every) + 1
        area = np.abs(
            (x[anchor] - avg_x) * (y[lo:hi] - y[anchor]) - (x[anchor] - x[lo:hi]) * (avg_y - y[anchor])
        )
        anchor = lo + int(np.argmax(area))
        picked[i + 1] = anchor
    return picked


def gap_markers(valid: np.ndarray, limit: int) -> np.ndarray:
    """First index of each null run that lies between two valid samples, longest runs first, at most `limit`.

    A chart breaks its line at a null value, so one marker per gap is enough to keep the gap visible.
    """
    if limit <= 0 or len(valid) == 0:
        return np.empty(0, dtype=np.int64)
    idx = np.flatnonzero(valid)
    if len(idx) < 2:
        return np.empty(0, dtype=np.int64)
    lengths = np.diff(idx) - 1
    gap_at = np.flatnonzero(lengths > 0)
    longest = gap_at[np.argsort(-lengths[gap_at], kind="stable")][:limit]
    return idx[longest] + 1


def select_indices(t: np.ndarray, series: Mapping[str, np.ndarray], points: int) -> np.ndarray:
    """Shared indices (ascending) of at most `points` samples for all `series` over the time axis `t`.

    Every series gets its own LTTB budget of `points // len(series)`, so the union of the picks never
    exceeds `points` and no series is dominated by another. The first and last sample are always kept.
    A series without a finite value contributes nothing; with at most `points` samples everything is kept.
    """
    n = len(t)
    if points < MIN_POINTS:
        raise ValueError(f"points must be at least {MIN_POINTS}, got {points}")
    if n <= points:
        return np.arange(n)
    if not series:
        series = {"": np.zeros(n)}
    budget = max(points // len(series), MIN_POINTS)
    x = np.asarray(t, dtype=float)
    chosen: set[int] = {0, n - 1}
    for values in series.values():
        y = np.asarray(values, dtype=float)
        valid = np.isfinite(y)
        if not valid.any():
            continue
        markers = gap_markers(valid, budget // 4)
        picks = lttb_indices(x[valid], y[valid], max(budget - len(markers), MIN_POINTS))
        chosen.update(np.flatnonzero(valid)[picks].tolist())
        chosen.update(markers.tolist())
    out = np.array(sorted(chosen), dtype=np.int64)
    if len(out) > points:  # only when there are more series than points // MIN_POINTS: keep the ends
        out = out[np.unique(np.linspace(0, len(out) - 1, points).round().astype(int))]
    return out
