"""HR and pace zones, time in zone – METRICS §1 (phase 2).

# METRICS §1
HR zones (Coggan, % of LTHR), half-open intervals on `r = hr / lthr`:
    Z1 r < 0.68, Z2 0.68 ≤ r < 0.84, Z3 0.84 ≤ r < 0.95, Z4 0.95 ≤ r ≤ 1.05, Z5 r > 1.05.
Run pace zones (% of threshold_speed), half-open intervals on `s = speed / threshold_speed`:
    Z1 s < 0.78, Z2 0.78 ≤ s < 0.88, Z3 0.88 ≤ s < 0.95, Z4 0.95 ≤ s ≤ 1.05, Z5 s > 1.05.
`time_in_zone` per activity: seconds of valid samples per zone, `{"1": s, …, "5": s}` with all five keys
present as integers. `threshold.zones` stores the bounds as
`{"hr": [0.68, 0.84, 0.95, 1.05], "pace": [0.78, 0.88, 0.95, 1.05]}` (clarified 2026-09-29).

Which samples are counted (kept samples of §0.2; pace zones on `gap_speed` of §3) is the caller's
choice – see `metrics/activity.py`. Ratios are formed by division (`value / threshold`), which is correctly
rounded, so a value exactly on a bound (e.g. 168 bpm at lthr 200) lands in the upper zone. Pure functions.
"""

import math
from collections.abc import Sequence
from itertools import pairwise

import numpy as np

HR_ZONE_BOUNDS: tuple[float, float, float, float] = (0.68, 0.84, 0.95, 1.05)
PACE_ZONE_BOUNDS: tuple[float, float, float, float] = (0.78, 0.88, 0.95, 1.05)
ZONE_KEYS: tuple[str, ...] = ("1", "2", "3", "4", "5")


def default_zones() -> dict:
    """The §1 bounds in the `threshold.zones` JSON shape (a fresh dict on every call)."""
    return {"hr": list(HR_ZONE_BOUNDS), "pace": list(PACE_ZONE_BOUNDS)}


def zone_of(ratio: np.ndarray, bounds: Sequence[float]) -> np.ndarray:
    """Zone number 1..5 per ratio per METRICS §1 (Z4 closed at both ends); 0 where the ratio is NaN.

    `bounds` = (b1, b2, b3, b4): Z1 < b1 ≤ Z2 < b2 ≤ Z3 < b3 ≤ Z4 ≤ b4 < Z5.
    """
    b1, b2, b3, b4 = _check_bounds(bounds)
    r = np.asarray(ratio, dtype=float)
    zone = 1 + (r >= b1).astype(np.int64) + (r >= b2) + (r >= b3) + (r > b4)
    return np.where(np.isnan(r), 0, zone).astype(np.int64)


def time_in_zones(values: np.ndarray, threshold: float, bounds: Sequence[float]) -> dict[str, int]:
    """Seconds (1 sample = 1 s) per zone of `values / threshold`; NaN values are not counted."""
    t = positive_number(threshold)
    if t is None:
        raise ValueError(f"threshold must be a positive number, got {threshold!r}")
    zones = zone_of(np.asarray(values, dtype=float) / t, bounds)
    counts = np.bincount(zones, minlength=6)
    return {key: int(counts[i]) for i, key in enumerate(ZONE_KEYS, start=1)}


def positive_number(value: object) -> float | None:
    """`value` as a float if it is a finite number > 0 (bool excluded), else None."""
    if isinstance(value, bool):
        return None
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _check_bounds(bounds: Sequence[float]) -> tuple[float, float, float, float]:
    values = tuple(float(b) for b in bounds)
    if len(values) != 4 or not all(math.isfinite(b) for b in values):
        raise ValueError(f"zone bounds must be 4 finite numbers, got {bounds!r}")
    if not all(a < b for a, b in pairwise(values)):
        raise ValueError(f"zone bounds must be strictly increasing, got {bounds!r}")
    return values  # type: ignore[return-value]
