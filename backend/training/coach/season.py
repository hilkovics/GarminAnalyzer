"""Season phases, weekly targets and CTL projection – METRICS §10.1–§10.2 (phase 6), recursion from §4.

Pure, deterministic functions; no I/O. Loads are TSS-equivalent points (1 h at threshold = 100).

# METRICS §10.1 (clarified 2026-09-29, phase 6): phases are per ISO week (Mon–Sun). `d` = days from the
# week's Monday to `R` (the goal with the earliest `race_date ≥ Monday`, chosen by the caller):
# `d > 84` Base, `21 < d ≤ 84` Build, `10 < d ≤ 21` Peak, `0 ≤ d ≤ 10` Taper. Weeks after `R` (and without
# any goal): the no-goal cycle, phase "Base", `k = (Monday − 2024-01-01).days // 7`, `k % 4 == 3` recovery.
#
# METRICS §10.2: `weekly_target_load = 7 · (CTL_now + 6 · ramp)`, ramp = 4 (Base), 5 (Build), 0 (Peak),
# Taper = 50 % of the last pre-taper week (not compounding). Recovery week: target · 0.70; with a goal only
# Base/Build weeks with `d // 7 ≥ 4` and `(d // 7) % 4 == 0`. Cap: `7 · (CTL_now + 6 / (1 − (41/42)^7))`.
# `CTL_now` = CTL of the day before the week's Monday; future weeks project CTL assuming each target is met
# as a constant daily load `T / 7`. Split: `run_share` = athlete split, else the 28-day run share of
# `load_run + load_bike`, 1.0 without load; run = `T · run_share`, bike = the rest.
#
# METRICS §4: `CTL[d] = CTL[d−1] + (daily_load[d] − CTL[d−1]) / 42`; `ramp_rate = CTL[d] − CTL[d−7]`.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta

PHASES = ("base", "build", "peak", "taper")
RAMP = {"base": 4.0, "build": 5.0, "peak": 0.0}  # target CTL increase per week (§10.2)
RECOVERY_FACTOR = 0.70
TAPER_FACTOR = 0.5
RAMP_CAP = 6.0  # max weekly CTL ramp (§4 warning threshold)
CYCLE_ANCHOR = date(2024, 1, 1)  # a Monday; k = 0 of the no-goal cycle (§10.1)
CTL_DAYS = 42

BASE_MIN_D = 85  # d > 84 → Base
BUILD_MIN_D = 22  # 21 < d ≤ 84 → Build
PEAK_MIN_D = 11  # 10 < d ≤ 21 → Peak; 0 ≤ d ≤ 10 → Taper
NO_GOAL_RECOVERY = 3  # k % 4 == 3
RECOVERY_EVERY = 4


@dataclass(frozen=True)
class WeekInfo:
    """Phase facts of one ISO week (METRICS §10.1–§10.2).

    `days_to_race` is `d` (None in the no-goal cycle); `cycle_k = (monday − CYCLE_ANCHOR).days // 7` is set
    for every week and drives the §10.3 template rotation.
    """

    monday: date
    phase: str
    recovery: bool
    days_to_race: int | None
    cycle_k: int


@dataclass(frozen=True)
class WeekTarget:
    """One week of the season plan (METRICS §10.2). `ctl_start` = CTL of the day before `monday`."""

    monday: date
    phase: str
    recovery: bool
    ctl_start: float
    target_load: float
    run_target: float
    bike_target: float
    days_to_race: int | None


def monday(d: date) -> date:
    """The Monday of `d`'s ISO week."""
    return d - timedelta(days=d.weekday())


def _require_monday(d: date, name: str) -> None:
    if d.weekday() != 0:
        raise ValueError(f"{name} must be a Monday, got {d.isoformat()} ({d.strftime('%A')})")


def _phase_for(d: int) -> str:
    """METRICS §10.1 clarified: phase from `d ≥ 0` days to the race."""
    if d >= BASE_MIN_D:
        return "base"
    if d >= BUILD_MIN_D:
        return "build"
    if d >= PEAK_MIN_D:
        return "peak"
    return "taper"


def week_info(week_monday: date, race_date: date | None) -> WeekInfo:
    """Phase, recovery flag, `d` and `cycle_k` of the week starting `week_monday` (METRICS §10.1–§10.2).

    `race_date` is the goal already chosen by the caller (earliest active `race_date ≥ Monday`); None or a
    date before the Monday means the no-goal cycle (phase "base", recovery when `k % 4 == 3`). With a goal,
    Base/Build weeks are recovery weeks when `d // 7 ≥ 4` and `(d // 7) % 4 == 0`; Peak/Taper never are.
    """
    _require_monday(week_monday, "week_monday")
    k = (week_monday - CYCLE_ANCHOR).days // 7
    if race_date is None or race_date < week_monday:
        return WeekInfo(week_monday, "base", k % RECOVERY_EVERY == NO_GOAL_RECOVERY, None, k)
    d = (race_date - week_monday).days
    phase = _phase_for(d)
    weeks = d // 7
    recovery = phase in ("base", "build") and weeks >= RECOVERY_EVERY and weeks % RECOVERY_EVERY == 0
    return WeekInfo(week_monday, phase, recovery, d, k)


def ramp_cap_target(ctl_now: float) -> float:
    """METRICS §10.2 cap: `7 · (CTL_now + 6 / (1 − (41/42)^7))` – a constant `T / 7` then ramps CTL by 6."""
    closed = 1.0 - ((CTL_DAYS - 1) / CTL_DAYS) ** 7
    return 7.0 * (ctl_now + RAMP_CAP / closed)


def weekly_target(ctl_now: float, info: WeekInfo, *, pre_taper_target: float | None = None) -> float:
    """Weekly target load in TSS-equivalent points (METRICS §10.2).

    - Taper: `TAPER_FACTOR · pre_taper_target`; without it the peak formula `7 · CTL_now` stands in for the
      pre-taper target (the pre-taper week is always Peak, ramp 0).
    - Otherwise `7 · (CTL_now + 6 · ramp)`, times `RECOVERY_FACTOR` in a recovery week.
    - Then capped at `ramp_cap_target(CTL_now)` and floored at 0.
    """
    if info.phase == "taper":
        pre = pre_taper_target if pre_taper_target is not None else 7.0 * (ctl_now + 6.0 * RAMP["peak"])
        target = TAPER_FACTOR * pre
    else:
        if info.phase not in RAMP:
            raise ValueError(f"unknown phase {info.phase!r}; expected one of {PHASES}")
        target = 7.0 * (ctl_now + 6.0 * RAMP[info.phase])
        if info.recovery:
            target *= RECOVERY_FACTOR
    return max(0.0, min(target, ramp_cap_target(ctl_now)))


def _clamp01(x: float) -> float:
    return min(1.0, max(0.0, x))


def split_targets(target: float, run_share: float) -> tuple[float, float]:
    """(run, bike) targets: run = `T · run_share` (clamped to [0, 1]), bike = the rest (METRICS §10.2)."""
    run = target * _clamp01(run_share)
    return run, target - run


def run_share(split: float | None, run_load_28: float, total_load_28: float) -> float:
    """METRICS §10.2 clarified: the athlete `run_bike_split`; if null (or NaN) the run share of
    `load_run + load_bike` over the last 28 days ("other" load is not planned; the caller passes run + bike as
    `total_load_28`); 1.0 if there is no load. Clamped to [0, 1].
    """
    if split is not None and not math.isnan(split):
        return _clamp01(split)
    if math.isnan(total_load_28) or total_load_28 <= 0 or math.isnan(run_load_28):
        return 1.0
    return _clamp01(run_load_28 / total_load_28)


def project_ctl(ctl0: float, daily_loads: Sequence[float]) -> list[float]:
    """CTL after each day of `daily_loads`, starting from `ctl0` = CTL of the day before (METRICS §4).

    `CTL[d] = CTL[d−1] + (daily_load[d] − CTL[d−1]) / 42`; the result has `len(daily_loads)` values.
    """
    out: list[float] = []
    ctl = float(ctl0)
    for load in daily_loads:
        ctl += (float(load) - ctl) / CTL_DAYS
        out.append(ctl)
    return out


def weekly_ramp(ctl_series: Sequence[float]) -> list[float]:
    """`CTL[d] − CTL[d−7]` aligned with `ctl_series`; NaN for the first 7 values (METRICS §4 clarified)."""
    values = [float(c) for c in ctl_series]
    return [math.nan if i < 7 else values[i] - values[i - 7] for i in range(len(values))]


def _virtual_pre_taper_target(first_monday: date, ctl_now: float, race_date: date | None) -> float:
    """Target of the last pre-taper week when the plan starts inside the taper (METRICS §10.2 clarified).

    That week lies before `first_monday` and its CTL is unknown here, so `ctl_now` stands in for it.
    """
    m = first_monday - timedelta(days=7)
    while True:
        info = week_info(m, race_date)
        if info.phase != "taper":
            return weekly_target(ctl_now, info)
        m -= timedelta(days=7)


def pre_taper_monday(week_monday: date, race_date: date | None) -> date:
    """Monday of the last non-taper week on or before `week_monday` (the §10.2 taper reference)."""
    m = week_monday
    while week_info(m, race_date).phase == "taper":
        m -= timedelta(days=7)
    return m


def season_plan(
    first_monday: date,
    weeks: int,
    ctl_now: float,
    race_date: date | None,
    run_share: float,
    *,
    pre_taper_target: float | None = None,
) -> list[WeekTarget]:
    """Weekly targets for `weeks` weeks from `first_monday` (METRICS §10.1–§10.2).

    `ctl_now` = CTL of the day before `first_monday`. CTL is projected forward assuming each week's target
    is met as a constant daily load `T / 7`. Taper weeks all use `TAPER_FACTOR ·` the target of the last
    pre-taper week (no compounding). If the plan starts inside the taper, pass that week's real target as
    `pre_taper_target` (the caller knows its stored CTL, review phase 6 B1); without it the week is computed
    virtually with `ctl_now` (see `_virtual_pre_taper_target`).
    """
    _require_monday(first_monday, "first_monday")
    if weeks < 0:
        raise ValueError(f"weeks must be ≥ 0, got {weeks}")
    plan: list[WeekTarget] = []
    ctl = float(ctl_now)
    pre_taper: float | None = pre_taper_target
    for i in range(weeks):
        m = first_monday + timedelta(days=7 * i)
        info = week_info(m, race_date)
        if info.phase == "taper":
            if pre_taper is None:
                pre_taper = _virtual_pre_taper_target(first_monday, ctl_now, race_date)
            target = weekly_target(ctl, info, pre_taper_target=pre_taper)
        else:
            target = weekly_target(ctl, info)
            pre_taper = target
        run, bike = split_targets(target, run_share)
        plan.append(WeekTarget(m, info.phase, info.recovery, ctl, target, run, bike, info.days_to_race))
        ctl = project_ctl(ctl, [target / 7.0] * 7)[-1]
    return plan
