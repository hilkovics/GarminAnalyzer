"""hrTSS, TRIMP, rTSS and the load sanity check – METRICS §2 (phase 2).

All loads are TSS-equivalent points (1 h at threshold = 100). Inputs are the kept samples of §0.2
(`metrics/preprocess.py`), 1 sample = 1 s. Primary load selection (§2.4) is in `metrics/activity.py`.
Pure functions, no I/O.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

from training.metrics.zones import positive_number

# ---------------------------------------------------------------- §2.1 hrTSS

# METRICS §2.1: relative HR r = hr / lthr → intensity factor, piecewise-linear through (r, IF):
IF_TABLE: tuple[tuple[float, float], ...] = (
    (0.50, 0.30),
    (0.68, 0.55),
    (0.83, 0.75),
    (0.94, 0.90),
    (1.00, 1.00),
    (1.05, 1.05),
    (1.15, 1.20),
)
_IF_R = np.array([r for r, _ in IF_TABLE])
_IF_V = np.array([v for _, v in IF_TABLE])


def intensity_factor_hr(r: np.ndarray) -> np.ndarray:
    """METRICS §2.1: clamp `r` to [0.50, 1.15], then interpolate linearly in `IF_TABLE`; NaN stays NaN."""
    r = np.asarray(r, dtype=float)
    out = np.full(r.shape, np.nan)
    valid = ~np.isnan(r)
    out[valid] = np.interp(np.clip(r[valid], _IF_R[0], _IF_R[-1]), _IF_R, _IF_V)
    return out


def hrtss(hr: np.ndarray, lthr: float) -> float:
    """METRICS §2.1: `hrTSS = Σ_i IF_i² · dt_i / 36` with `dt_i = 1 s`, `IF_i = IF(hr_i / lthr)`.

    Samples with NaN HR contribute 0 (clarified 2026-09-29), so no HR at all gives 0.0.
    """
    threshold = positive_number(lthr)
    if threshold is None:
        raise ValueError(f"lthr must be a positive number, got {lthr!r}")
    hr = np.asarray(hr, dtype=float)
    hr = hr[~np.isnan(hr)]
    return float(np.sum(intensity_factor_hr(hr / threshold) ** 2) / 36.0)


def activity_if_hr(hrtss_value: float, moving_s: int) -> float | None:
    """METRICS §2.1: `IF_hr = sqrt(hrTSS · 36 / moving_s)`; None without moving time.

    `moving_s` is the §0.2 count including samples without HR (clarified 2026-09-29).
    """
    if moving_s <= 0:
        return None
    return math.sqrt(hrtss_value * 36.0 / moving_s)


# ---------------------------------------------------------------- §2.2 TRIMP

# METRICS §2.2: per-minute weighting a · e^(b · HRr).
TRIMP_CONSTANTS: dict[str, tuple[float, float]] = {"male": (0.64, 1.92), "female": (0.86, 1.67)}


def trimp(hr: np.ndarray, rest_hr: float, max_hr: float, sex: str) -> float:
    """METRICS §2.2 Banister TRIMP over the valid samples (`dt_i = 1 s`).

    `HRr_i = (hr_i − rest_hr) / (max_hr − rest_hr)`, clamped to [0, 1];
    male `TRIMP = Σ_i (dt_i/60) · HRr_i · 0.64 · e^(1.92·HRr_i)`, female `0.86 · e^(1.67·HRr_i)`.
    """
    a, b = _trimp_constants(sex)
    hrr = _hrr(np.asarray(hr, dtype=float), rest_hr, max_hr)
    hrr = hrr[~np.isnan(hrr)]
    return float(np.sum(hrr * a * np.exp(b * hrr)) / 60.0)


def trimp_norm(trimp_value: float, *, rest_hr: float, max_hr: float, lthr: float, sex: str) -> float:
    """METRICS §2.2: `TRIMP_norm = TRIMP · 100 / TRIMP_ref`, `TRIMP_ref` = TRIMP of 60 min at hr == lthr.

    Raises ValueError when TRIMP_ref is 0 (lthr ≤ rest_hr), which the spec leaves undefined.
    """
    a, b = _trimp_constants(sex)
    hrr_lthr = float(_hrr(np.array([float(lthr)]), rest_hr, max_hr)[0])
    trimp_ref = 60.0 * hrr_lthr * a * math.exp(b * hrr_lthr)  # 60 one-minute terms of equal HRr
    if not trimp_ref > 0:
        raise ValueError(f"TRIMP_ref is 0 for lthr {lthr!r} ≤ rest_hr {rest_hr!r}")
    return float(trimp_value) * 100.0 / trimp_ref


def _trimp_constants(sex: str) -> tuple[float, float]:
    if sex not in TRIMP_CONSTANTS:
        raise ValueError(f"sex must be 'male' or 'female', got {sex!r}")
    return TRIMP_CONSTANTS[sex]


def _hrr(hr: np.ndarray, rest_hr: float, max_hr: float) -> np.ndarray:
    rest, peak = positive_number(rest_hr), positive_number(max_hr)
    if rest is None or peak is None or peak <= rest:
        raise ValueError(f"need 0 < rest_hr < max_hr, got rest_hr={rest_hr!r}, max_hr={max_hr!r}")
    return np.clip((hr - rest) / (peak - rest), 0.0, 1.0)  # NaN stays NaN


# ---------------------------------------------------------------- §2.3 rTSS

NGS_WINDOW = 30  # §2.3 rolling_mean_30s, samples
NGS_MIN_WINDOWS = 30  # §2.3 clarified: fewer valid windows → rTSS null
GPS_MIN_SPEED_SHARE = 0.90  # §2.3 usable GPS


def normalized_graded_speed(gap_speed: np.ndarray) -> float | None:
    """METRICS §2.3: `NGS = ( mean( rolling_mean_30s(gap_speed)^4 ) )^(1/4)` over the kept samples.

    Clarified 2026-09-29: `rolling_mean_30s` is a trailing 30-sample mean; windows containing NaN are
    skipped, and fewer than 30 valid windows → None. Only full windows count, so the first one ends at
    sample 29 (at least 59 samples are needed).
    """
    gap = np.asarray(gap_speed, dtype=float)
    if len(gap) < NGS_WINDOW:
        return None
    means = np.lib.stride_tricks.sliding_window_view(gap, NGS_WINDOW).mean(axis=1)
    means = means[~np.isnan(means)]
    if len(means) < NGS_MIN_WINDOWS:
        return None
    return float(np.sqrt(np.sqrt(np.mean(means**4))))


def rtss(gap_speed: np.ndarray, moving_s: int, threshold_speed: float) -> tuple[float, float] | None:
    """METRICS §2.3: `IF_pace = NGS / threshold_speed`, `rTSS = moving_s · IF_pace² / 36`.

    Returns `(rtss, if_pace)`, or None when NGS is undefined (fewer than 30 valid windows). Whether the
    activity qualifies at all (a run with usable GPS) is checked by the caller with `usable_gps`.
    """
    ts = positive_number(threshold_speed)
    if ts is None:
        raise ValueError(f"threshold_speed must be a positive number, got {threshold_speed!r}")
    ngs = normalized_graded_speed(gap_speed)
    if ngs is None:
        return None
    if_pace = ngs / ts
    return moving_s * if_pace**2 / 36.0, if_pace


def usable_gps(samples: pd.DataFrame, is_indoor: bool) -> bool:
    """METRICS §2.3 usable GPS: distance stream present, `≥ 90 %` of moving samples with speed, not
    treadmill/indoor. `samples` = the kept samples (`Preprocessed.samples`).

    Clarified 2026-09-29: "distance stream present" = at least one non-NaN distance value.
    """
    if is_indoor or len(samples) == 0:
        return False
    distance = pd.to_numeric(samples["distance"], errors="coerce")
    speed = pd.to_numeric(samples["speed"], errors="coerce")
    if not distance.notna().any():
        return False
    return bool(speed.notna().sum() / len(samples) >= GPS_MIN_SPEED_SHARE)


# ---------------------------------------------------------------- §2.5 sanity check

SANITY_GOOD, SANITY_FAIR = 0.8, 0.7  # §2.5: expect r > 0.8, below 0.7 → warning
SANITY_MIN_N = 3  # §2.5 clarified


@dataclass(frozen=True)
class LoadSanity:
    """METRICS §2.5 result. `status`: "good" (r > 0.8), "fair" (0.7 ≤ r ≤ 0.8), "warning" (r < 0.7),
    "insufficient" (n < 3, or r undefined because one side has no variance)."""

    r: float | None
    n: int
    status: str


def load_sanity(load_primary: Sequence[float | None], garmin_load: Sequence[float | None]) -> LoadSanity:
    """METRICS §2.5: Pearson r between `load_primary` and Garmin `training_load` over the activities with
    both present (pairs with None/NaN on either side are dropped). Needs at least 3 pairs."""
    if len(load_primary) != len(garmin_load):
        raise ValueError(f"length mismatch: {len(load_primary)} vs {len(garmin_load)}")
    x, y = _floats_or_nan(load_primary), _floats_or_nan(garmin_load)
    both = ~np.isnan(x) & ~np.isnan(y)
    x, y = x[both], y[both]
    n = len(x)
    if n < SANITY_MIN_N:
        return LoadSanity(r=None, n=n, status="insufficient")
    dx, dy = x - x.mean(), y - y.mean()
    denom = math.sqrt(float(np.sum(dx * dx)) * float(np.sum(dy * dy)))
    if denom == 0:
        return LoadSanity(r=None, n=n, status="insufficient")
    r = min(1.0, max(-1.0, float(np.sum(dx * dy)) / denom))
    if r > SANITY_GOOD:
        status = "good"
    elif r >= SANITY_FAIR:
        status = "fair"
    else:
        status = "warning"
    return LoadSanity(r=r, n=n, status=status)


def _floats_or_nan(values: Sequence[float | None]) -> np.ndarray:
    return np.array([np.nan if v is None else float(v) for v in values], dtype=float)
