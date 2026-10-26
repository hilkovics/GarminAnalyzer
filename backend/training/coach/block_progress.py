"""Block progress of the coach "Kondícia" (METRICS §11.4): fitness snapshots, check runs, week records and
the block summary. Pure functions over pandas frames and plain values – no I/O.

Units: pace as speed in m/s (higher = faster), EF in m/min/bpm, times in seconds.
"""

import math
import statistics
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, timedelta

import pandas as pd

from training.metrics.efficiency import TREND_WINDOW_DAYS, ef_trend
from training.metrics.predictions import pick_reference, vdot, vdot_race_time

CHECK_RUN_S = 1800.0
GREEN_FROM = 70.0
DISTANCES = {"t5k_s": 5000.0, "t10k_s": 10000.0}


@dataclass(frozen=True)
class Snapshot:
    """§11.4 fitness on `day`; every part is None without data."""

    day: date
    pace_at_ref_hr: float | None = None  # m/s
    ef: float | None = None
    vdot: float | None = None
    t5k_s: float | None = None
    t10k_s: float | None = None
    reference_date: date | None = None


@dataclass(frozen=True)
class Change:
    """Week value − baseline: pace and EF + = better, times − = better."""

    pace_at_ref_hr: float | None
    ef: float | None
    vdot: float | None
    t5k_s: float | None
    t10k_s: float | None


@dataclass(frozen=True)
class CheckRun:
    day: date
    activity_id: int
    distance_m: float  # in 30 min
    avg_hr: float | None
    vdot: float
    t5k_s: float
    t10k_s: float


@dataclass(frozen=True)
class WeekRecord:
    monday: date
    week_no: int
    target_s: float
    run_s: float
    items_done: int
    brake: str | None
    recovery: bool
    test: bool
    mean_readiness: float | None
    mean_sleep_s: float | None
    value: Snapshot


@dataclass(frozen=True)
class Summary:
    final: bool  # week 12 is over
    weeks: int
    items_done: int
    items_planned: int
    run_s: float
    target_s: float
    brake_weeks: int
    mean_readiness: float | None
    mean_sleep_s: float | None
    green_share: float | None
    change: Change | None


def _finite(value: object) -> float | None:
    if value is None:
        return None
    number = float(value)  # type: ignore[arg-type]
    return number if math.isfinite(number) else None


def _window(runs: pd.DataFrame, day: date) -> pd.DataFrame:
    dates = pd.to_datetime(runs["local_date"]).dt.date
    return runs[(dates >= day - timedelta(days=TREND_WINDOW_DAYS - 1)) & (dates <= day)]


def snapshot(day: date, runs: pd.DataFrame, candidates: pd.DataFrame) -> Snapshot:
    """§11.4 snapshot on `day`.

    `runs`: one row per run (commutes excluded) with `local_date, ef, steady_state, pace_at_ref_hr_day`.
    `candidates`: the §7 candidates (`local_date, distance_m, time_s, source`).
    """
    pace = ef = None
    if not runs.empty:
        window = pd.to_numeric(_window(runs, day)["pace_at_ref_hr_day"], errors="coerce").dropna()
        pace = _finite(window.median()) if not window.empty else None
        ef = _finite(ef_trend(runs, [day]).iloc[0])
    reference = pick_reference(candidates, today=day) if not candidates.empty else None
    if reference is None:
        return Snapshot(day, pace, ef)
    times = {key: vdot_race_time(reference.vdot, metres) for key, metres in DISTANCES.items()}
    return Snapshot(day, pace, ef, reference.vdot, times["t5k_s"], times["t10k_s"], reference.local_date)


def _diff(new: float | None, old: float | None) -> float | None:
    return None if new is None or old is None else new - old


def change(baseline: Snapshot, value: Snapshot) -> Change:
    return Change(
        pace_at_ref_hr=_diff(value.pace_at_ref_hr, baseline.pace_at_ref_hr),
        ef=_diff(value.ef, baseline.ef),
        vdot=_diff(value.vdot, baseline.vdot),
        t5k_s=_diff(value.t5k_s, baseline.t5k_s),
        t10k_s=_diff(value.t10k_s, baseline.t10k_s),
    )


def check_run_result(
    day: date, activity_id: int, distance_m: float | None, avg_hr: float | None
) -> CheckRun | None:
    """§11.4: Daniels equivalents from the 30-min effort (distance in 1800 s); None without an effort."""
    distance = _finite(distance_m)
    if distance is None or distance <= 0:
        return None
    value = vdot(distance, CHECK_RUN_S)
    return CheckRun(
        day=day,
        activity_id=activity_id,
        distance_m=distance,
        avg_hr=_finite(avg_hr),
        vdot=value,
        t5k_s=vdot_race_time(value, DISTANCES["t5k_s"]),
        t10k_s=vdot_race_time(value, DISTANCES["t10k_s"]),
    )


def mean(values: Sequence[float | None]) -> float | None:
    """Mean of the finite values, None if there are none."""
    clean = [v for v in (_finite(x) for x in values) if v is not None]
    return statistics.fmean(clean) if clean else None


def summarize(
    weeks: Sequence[WeekRecord],
    baseline: Snapshot | None,
    *,
    final: bool,
    readiness: Sequence[float | None],
    sleep_s: Sequence[float | None],
) -> Summary:
    """§11.4 block summary over the elapsed `weeks`; `readiness` / `sleep_s` are the block's daily values."""
    ready = [v for v in (_finite(x) for x in readiness) if v is not None]
    last = weeks[-1].value if weeks else None
    return Summary(
        final=final,
        weeks=len(weeks),
        items_done=sum(w.items_done for w in weeks),
        items_planned=3 * len(weeks),
        run_s=sum(w.run_s for w in weeks),
        target_s=sum(w.target_s for w in weeks),
        brake_weeks=sum(1 for w in weeks if w.brake),
        mean_readiness=statistics.fmean(ready) if ready else None,
        mean_sleep_s=mean(sleep_s),
        green_share=sum(1 for v in ready if v >= GREEN_FROM) / len(ready) if ready else None,
        change=change(baseline, last) if baseline is not None and last is not None else None,
    )


# --- storage of the baseline (CoachBlock.baseline JSON) ---------------------------------------------------


def to_json(value: Snapshot) -> dict[str, object]:
    return {
        "day": value.day.isoformat(),
        "pace_at_ref_hr": value.pace_at_ref_hr,
        "ef": value.ef,
        "vdot": value.vdot,
        "t5k_s": value.t5k_s,
        "t10k_s": value.t10k_s,
        "reference_date": value.reference_date.isoformat() if value.reference_date else None,
    }


def from_json(data: dict[str, object] | None) -> Snapshot | None:
    """The stored baseline, or None for a missing or malformed value (it is then computed again)."""
    if not isinstance(data, dict):
        return None
    try:
        day = date.fromisoformat(str(data["day"]))
        ref = data.get("reference_date")
        reference = date.fromisoformat(str(ref)) if ref else None
        parts = {key: _finite(data.get(key)) for key in ("pace_at_ref_hr", "ef", "vdot", "t5k_s", "t10k_s")}
    except (KeyError, TypeError, ValueError):
        return None
    return replace(Snapshot(day), **parts, reference_date=reference)  # type: ignore[arg-type]
