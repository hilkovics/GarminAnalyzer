"""Speed–HR curve – METRICS §6.1 (phase 4), plus the §9 single-activity `pace_at_ref_hr_day`.

# METRICS §6.1
For a trailing 28-day window: pool 60 s aggregates (mean gap_speed, mean HR with 30 s lag) from all runs,
excluding first 600 s and walking. Bin HR in 5 bpm bins; per bin take the median gap_speed, require ≥ 10
aggregates per bin. `pace_at_ref_hr` = value in the bin containing `ref_hr = 0.80·lthr` (configurable).
(Clarified 2026-09-29, phase 4:
- 60 s aggregate = a consecutive non-overlapping block of 60 kept samples (after the first 600 s, lagged
  pairs, not slow) in which every sample has valid gap_speed and lagged HR; mean gap_speed and mean HR.
- Bin = `floor(mean_hr / 5) · 5` (label = lower edge). Bins with < 10 aggregates are omitted.
- `ref_hr = 0.80 · lthr` of the run threshold valid at the window end; `pace_at_ref_hr` = the median of the
  bin containing `ref_hr`, null if that bin is omitted.
- Snapshot JSON: `{"bins": {"145": v, …}, "counts": {…}, "ref_hr": x, "pace_at_ref_hr": v}`.
- `pace_at_ref_hr_day` (§9) = median gap_speed of that activity's own 60 s aggregates with mean HR in
  `[ref_hr − 5, ref_hr + 5]`; needs ≥ 20 such aggregates, else null.)

# METRICS §0.6 (revised)
Pair by time: `hr_lagged(t) = hr(t + 30)` if the kept sample at t + 30 exists, else NaN; a pause inside
(t, t + 30] gives no partner (see `preprocess.has_lag_partner` / `lag_hr`).

Interpretation: the parenthesis "(after the first 600 s, lagged pairs, not slow)" is read as the sample set
that is cut into blocks – kept samples from position 600 on that have a lagged partner (so the 30 samples
before a pause and the last 30 kept samples are removed, not NaN), with slow samples removed. That set is
cut into consecutive 60-sample blocks from its first sample (last partial block dropped); a block with any
NaN gap_speed / lagged HR (e.g. a partner whose HR is invalid) is dropped.
Pooling over the 28-day window (concatenating the runs' aggregates) is the caller's job.

Pure functions, no I/O.
"""

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from training.metrics.preprocess import HR_LAG_S, Preprocessed, has_lag_partner, lag_hr

AGGREGATE_S = 60  # §6.1 block length (samples)
BIN_BPM = 5  # §6.1 bin width
MIN_PER_BIN = 10  # §6.1
REF_FRACTION = 0.80  # §6.1 ref_hr = 0.80 · lthr (configurable)
MIN_DAY_AGGREGATES = 20  # §9 "≥ 20 min in the reference bin ± 5 bpm"
DAY_BAND_BPM = 5.0  # §6.1 clarified: [ref_hr − 5, ref_hr + 5]
WARMUP_S = 600  # §6.1 first 600 s excluded
AGGREGATE_COLUMNS: tuple[str, ...] = ("gap_speed", "hr")
_BIN_ROUND_DIGITS = 9  # floor(x / 5) on x rounded to 1e-9 bpm, so 0.8 · 175 = 140.00000000000003 → 140


@dataclass(frozen=True)
class SpeedHrCurve:
    """METRICS §6.1 curve: `bins` lower bin edge (bpm) → median gap_speed (m/s) for bins with ≥ 10
    aggregates, `counts` the aggregates per included bin (same keys), `ref_hr` (bpm) and
    `pace_at_ref_hr` (m/s; the presentation layer converts to min/km)."""

    bins: dict[int, float]
    counts: dict[int, int]
    ref_hr: float | None
    pace_at_ref_hr: float | None


def aggregates_60s(prep: Preprocessed) -> pd.DataFrame:
    """METRICS §6.1 60 s aggregates of one activity: columns `gap_speed, hr` (mean gap_speed, mean lagged
    HR), one row per qualifying block, in time order."""
    s = prep.samples
    n = len(s)
    empty = pd.DataFrame({c: pd.Series(dtype=float) for c in AGGREGATE_COLUMNS})
    if n <= WARMUP_S:
        return empty
    gap = s["gap_speed"].to_numpy(dtype=float)
    t = s["t"].to_numpy(dtype=np.int64)
    hr_lag = lag_hr(t, s["hr"].to_numpy(dtype=float), HR_LAG_S)
    pos = np.arange(n)
    in_set = (pos >= WARMUP_S) & has_lag_partner(t, HR_LAG_S) & ~s["is_slow"].to_numpy(dtype=bool)
    gap, hr_lag = gap[in_set], hr_lag[in_set]
    n_blocks = len(gap) // AGGREGATE_S
    if n_blocks == 0:
        return empty
    gap_blocks = gap[: n_blocks * AGGREGATE_S].reshape(n_blocks, AGGREGATE_S)
    hr_blocks = hr_lag[: n_blocks * AGGREGATE_S].reshape(n_blocks, AGGREGATE_S)
    ok = ~np.isnan(gap_blocks).any(axis=1) & ~np.isnan(hr_blocks).any(axis=1)
    return pd.DataFrame(
        {"gap_speed": gap_blocks[ok].mean(axis=1), "hr": hr_blocks[ok].mean(axis=1)},
        columns=list(AGGREGATE_COLUMNS),
    )


def hr_bin(hr: float) -> int:
    """METRICS §6.1 bin label `floor(hr / 5) · 5` (lower edge; 145 = [145, 150))."""
    return math.floor(round(float(hr), _BIN_ROUND_DIGITS) / BIN_BPM) * BIN_BPM


def speed_hr_curve(
    aggregates: pd.DataFrame, *, lthr: float | None, ref_fraction: float = REF_FRACTION
) -> SpeedHrCurve:
    """METRICS §6.1 curve over pooled 60 s aggregates (columns `gap_speed`, `hr`).

    `lthr` is the run threshold valid at the window end (None → `ref_hr` and `pace_at_ref_hr` null).
    """
    hr = pd.to_numeric(aggregates["hr"], errors="coerce").to_numpy(dtype=float)
    gap = pd.to_numeric(aggregates["gap_speed"], errors="coerce").to_numpy(dtype=float)
    ok = ~np.isnan(hr) & ~np.isnan(gap)
    labels = np.array([hr_bin(h) for h in hr[ok]], dtype=np.int64)
    gap = gap[ok]
    bins: dict[int, float] = {}
    counts: dict[int, int] = {}
    for label in np.unique(labels):
        values = gap[labels == label]
        if len(values) >= MIN_PER_BIN:
            bins[int(label)] = float(np.median(values))
            counts[int(label)] = len(values)
    ref_hr = None if lthr is None else float(ref_fraction * lthr)
    pace = None if ref_hr is None else bins.get(hr_bin(ref_hr))
    return SpeedHrCurve(bins=bins, counts=counts, ref_hr=ref_hr, pace_at_ref_hr=pace)


def pace_at_ref_hr_day(aggregates: pd.DataFrame, ref_hr: float | None) -> float | None:
    """METRICS §6.1 / §9: median gap_speed of one activity's aggregates with mean HR in
    `[ref_hr − 5, ref_hr + 5]` (inclusive); None with fewer than 20 of them or without `ref_hr`."""
    if ref_hr is None or aggregates.empty:
        return None
    hr = pd.to_numeric(aggregates["hr"], errors="coerce").to_numpy(dtype=float)
    gap = pd.to_numeric(aggregates["gap_speed"], errors="coerce").to_numpy(dtype=float)
    in_band = (hr >= ref_hr - DAY_BAND_BPM) & (hr <= ref_hr + DAY_BAND_BPM) & ~np.isnan(gap)
    if np.count_nonzero(in_band) < MIN_DAY_AGGREGATES:
        return None
    return float(np.median(gap[in_band]))


def curve_to_json(curve: SpeedHrCurve) -> dict:
    """The §6.1 `curve_snapshot` JSON shape: string bin keys in ascending order, plain floats/ints."""
    order = sorted(curve.bins)
    return {
        "bins": {str(b): float(curve.bins[b]) for b in order},
        "counts": {str(b): int(curve.counts[b]) for b in order},
        "ref_hr": None if curve.ref_hr is None else float(curve.ref_hr),
        "pace_at_ref_hr": None if curve.pace_at_ref_hr is None else float(curve.pace_at_ref_hr),
    }
