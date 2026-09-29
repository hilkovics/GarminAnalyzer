"""Per-activity metrics: §0 preprocessing → zones (§1), loads (§2.1–§2.3), primary load (§2.4) – phase 2.

Pure orchestration of `preprocess`, `zones`, `gap` and `load` for one activity. Resolving the threshold
record (latest `valid_from ≤ local_date` for the activity's sport, `other` → the run record's LTHR only) and
`rest_hr` (override, else the 28-day RHR median) is the caller's job (`training/pipeline.py`); this module
receives the resolved values.

# METRICS §2.4
- run → `rTSS` if available else `hrTSS`
- bike, other → `hrTSS`
- if `low_confidence` and Garmin `training_load` present → keep computed value but flag; do **not**
  substitute.

Null rules (METRICS §1, §2.1–§2.3 clarified 2026-09-29):
- no `lthr` → `hrtss`, `if_hr`, `trimp_norm`, `time_in_hr_zone` are None;
- no valid HR sample (`hr_coverage == 0`, §2.1 changed 2026-09-29) → `hrtss`, `if_hr`, `trimp_norm` are
  None (unknown, not 0); `time_in_hr_zone` stays the all-zero count; the activity is `low_confidence`;
- `trimp_norm` also None without `sex` / `max_hr` / `rest_hr`, or with `max_hr ≤ rest_hr` (and when
  `lthr ≤ rest_hr`, where TRIMP_ref is 0);
- `rtss` / `if_pace` only for runs with usable GPS and a `threshold_speed`, and None with fewer than 30
  valid 30 s windows;
- `time_in_pace_zone` for runs with a `threshold_speed` (on `gap_speed`, samples with a speed);
- no load at all → `load_primary` and `load_method` None (e.g. a ride without HR; a run without HR keeps
  rTSS when it has usable GPS and a `threshold_speed`).
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from training.metrics.load import (
    activity_if_hr,
    hrtss,
    rtss,
    trimp,
    trimp_norm,
    usable_gps,
)
from training.metrics.preprocess import SPORTS, preprocess
from training.metrics.zones import (
    HR_ZONE_BOUNDS,
    PACE_ZONE_BOUNDS,
    default_zones,
    positive_number,
    time_in_zones,
)


@dataclass(frozen=True)
class ThresholdParams:
    """The threshold record valid at the activity's local date (METRICS §1), already resolved."""

    lthr: float | None = None
    threshold_speed: float | None = None  # m/s, runs only
    zones: dict | None = None  # {"hr": [4 bounds], "pace": [4 bounds]}; None → default_zones()


@dataclass(frozen=True)
class AthleteParams:
    """Athlete values for TRIMP (METRICS §2.2)."""

    sex: str | None = None  # "male" | "female"
    max_hr: float | None = None
    rest_hr: float | None = None  # already resolved by the caller (override or 28-day median)


@dataclass(frozen=True)
class ActivityMetrics:
    """The `activity_metric` columns computed in phase 2 (METRICS §0–§2.4)."""

    moving_s: int
    hr_coverage: float
    low_confidence: bool
    hrtss: float | None
    if_hr: float | None
    trimp_norm: float | None
    rtss: float | None
    if_pace: float | None
    load_primary: float | None
    load_method: str | None  # "rtss" | "hrtss" | None
    time_in_hr_zone: dict[str, int] | None
    time_in_pace_zone: dict[str, int] | None  # runs with threshold_speed only


def activity_metrics(
    streams: pd.DataFrame,
    *,
    sport: str,
    is_indoor: bool,
    threshold: ThresholdParams,
    athlete: AthleteParams,
) -> ActivityMetrics:
    """All phase-2 metrics of one activity from its `activity_stream` rows (see the module docstring)."""
    if sport not in SPORTS:
        raise ValueError(f"sport must be one of {SPORTS}, got {sport!r}")
    pre = preprocess(streams, sport)
    samples = pre.samples
    hr = samples["hr"].to_numpy()
    gap = samples["gap_speed"].to_numpy()
    zones = threshold.zones if threshold.zones is not None else default_zones()
    lthr = positive_number(threshold.lthr)
    threshold_speed = positive_number(threshold.threshold_speed) if sport == "run" else None

    # §2.1 hrTSS / IF_hr, §2.2 TRIMP_norm, §1 HR zones – all need LTHR. Without any valid HR sample the
    # load functions return None (§2.1 changed 2026-09-29), which also makes load_primary None below
    # unless §2.4 picks rTSS.
    hrtss_value = if_hr_value = trimp_norm_value = None
    time_in_hr_zone = None
    if lthr is not None:
        hrtss_value = hrtss(hr, lthr)
        if_hr_value = activity_if_hr(hrtss_value, pre.moving_s)
        trimp_norm_value = _trimp_norm(hr, lthr, athlete)
        time_in_hr_zone = time_in_zones(hr, lthr, zones.get("hr", HR_ZONE_BOUNDS))

    # §2.3 rTSS / IF_pace and §1 pace zones – runs with a threshold speed.
    rtss_value = if_pace_value = None
    time_in_pace_zone = None
    if threshold_speed is not None:
        if usable_gps(samples, is_indoor):
            result = rtss(gap, pre.moving_s, threshold_speed)
            if result is not None:
                rtss_value, if_pace_value = (float(v) for v in result)
        time_in_pace_zone = time_in_zones(gap, threshold_speed, zones.get("pace", PACE_ZONE_BOUNDS))

    # §2.4 primary load: low_confidence is only a flag, never a reason to substitute.
    if sport == "run" and rtss_value is not None:
        load_primary, load_method = rtss_value, "rtss"
    elif hrtss_value is not None:
        load_primary, load_method = hrtss_value, "hrtss"
    else:
        load_primary, load_method = None, None

    return ActivityMetrics(
        moving_s=int(pre.moving_s),
        hr_coverage=float(pre.hr_coverage),
        low_confidence=bool(pre.low_confidence),
        hrtss=hrtss_value,
        if_hr=if_hr_value,
        trimp_norm=trimp_norm_value,
        rtss=rtss_value,
        if_pace=if_pace_value,
        load_primary=load_primary,
        load_method=load_method,
        time_in_hr_zone=time_in_hr_zone,
        time_in_pace_zone=time_in_pace_zone,
    )


def _trimp_norm(hr: np.ndarray, lthr: float, athlete: AthleteParams) -> float | None:
    """METRICS §2.2 TRIMP_norm, or None when the athlete data is incomplete or TRIMP_ref is 0."""
    rest, peak = positive_number(athlete.rest_hr), positive_number(athlete.max_hr)
    if athlete.sex not in ("male", "female") or rest is None or peak is None or peak <= rest or lthr <= rest:
        return None
    value = trimp(hr, rest, peak, athlete.sex)
    return trimp_norm(value, rest_hr=rest, max_hr=peak, lthr=lthr, sex=athlete.sex)
