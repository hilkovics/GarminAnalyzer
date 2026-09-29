"""Season phases, weekly targets, CTL projection (METRICS §4, §10.1–§10.2 incl. the phase-6 clarifications).

Expected values are hand-computed in the comments. `Q = 1 − (41/42)^7` is the share of the gap
`L − CTL` that a constant daily load `L` closes in 7 days (§10.2 clarification).
"""

import math
from datetime import date, timedelta

import pytest

from training.coach import season
from training.coach.season import (
    CTL_DAYS,
    CYCLE_ANCHOR,
    PHASES,
    RAMP,
    RAMP_CAP,
    RECOVERY_FACTOR,
    TAPER_FACTOR,
    WeekInfo,
    WeekTarget,
    monday,
    project_ctl,
    ramp_cap_target,
    run_share,
    season_plan,
    split_targets,
    week_info,
    weekly_ramp,
    weekly_target,
)

TOL = 1e-9
Q = 1 - (41 / 42) ** 7
M = date(2026, 10, 5)  # a Monday
WEIGHTS = {"rest": 0.0, "easy": 1.0, "long": 2.0, "q1": 1.25, "q2": 1.25}


def info(phase: str, *, recovery: bool = False, d: int | None = 50) -> WeekInfo:
    return WeekInfo(monday=M, phase=phase, recovery=recovery, days_to_race=d, cycle_k=0)


# ---------------------------------------------------------------------------------------------------------
# constants and monday()
# ---------------------------------------------------------------------------------------------------------


def test_constants() -> None:
    assert PHASES == ("base", "build", "peak", "taper")
    assert RAMP == {"base": 4.0, "build": 5.0, "peak": 0.0}
    assert (RECOVERY_FACTOR, TAPER_FACTOR, RAMP_CAP, CTL_DAYS) == (0.70, 0.5, 6.0, 42)
    assert (CYCLE_ANCHOR, CYCLE_ANCHOR.weekday()) == (date(2024, 1, 1), 0)


@pytest.mark.parametrize("offset", range(7))
def test_monday(offset: int) -> None:
    assert monday(M + timedelta(days=offset)) == M


# ---------------------------------------------------------------------------------------------------------
# §10.1 phases
# ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("d", "phase"),
    [
        (120, "base"),
        (85, "base"),
        (84, "build"),
        (22, "build"),
        (21, "peak"),
        (11, "peak"),
        (10, "taper"),
        (0, "taper"),
    ],
)
def test_phase_boundaries(d: int, phase: str) -> None:
    wi = week_info(M, M + timedelta(days=d))
    assert wi.phase == phase
    assert wi.days_to_race == d
    assert wi.monday == M


def test_race_before_monday_is_the_no_goal_cycle() -> None:
    wi = week_info(M, M - timedelta(days=1))  # d = −1
    assert wi.phase == "base"
    assert wi.days_to_race is None
    wi_none = week_info(M, None)
    assert (wi_none.phase, wi_none.days_to_race) == ("base", None)
    assert wi == wi_none


def test_cycle_k_and_no_goal_recovery_every_fourth_week() -> None:
    # k = (Monday − 2024-01-01).days // 7; k % 4 == 3 is the recovery week
    mondays = [CYCLE_ANCHOR + timedelta(weeks=i) for i in range(9)]
    infos = [week_info(m, None) for m in mondays]
    assert [i.cycle_k for i in infos] == list(range(9))
    assert [i.recovery for i in infos] == [False, False, False, True] * 2 + [False]
    assert all(i.phase == "base" for i in infos)
    # before the anchor: k = −1 → −1 % 4 == 3 → recovery (floor division, no gap in the cycle)
    before = week_info(date(2023, 12, 25), None)
    assert (before.cycle_k, before.recovery) == (-1, True)
    # 2026-10-05: (2026-10-05 − 2024-01-01) = 1008 days = 144 weeks → k = 144, 144 % 4 = 0
    assert week_info(M, None).cycle_k == 144
    # cycle_k is set with a goal too (template rotation)
    assert week_info(M, M + timedelta(days=40)).cycle_k == 144


def test_week_info_rejects_non_monday() -> None:
    with pytest.raises(ValueError, match="Monday"):
        week_info(M + timedelta(days=1), None)


@pytest.mark.parametrize(
    ("d", "recovery"),
    [
        (118, True),  # d // 7 = 16, base
        (112, True),  # 16
        (91, False),  # 13
        (90, True),  # 12, base
        (85, True),  # 12, base
        (84, True),  # 12, build
        (83, False),  # 11
        (63, False),  # 9
        (62, True),  # 8
        (56, True),  # 8
        (35, False),  # 5
        (34, True),  # 4
        (28, True),  # 4, build
        (27, False),  # 3
        (21, False),  # peak
        (14, False),  # peak
        (7, False),  # taper, d // 7 = 1
        (6, False),  # taper, d // 7 = 0 (0 % 4 == 0 but < 4)
        (0, False),
    ],
)
def test_recovery_with_goal(d: int, recovery: bool) -> None:
    wi = week_info(M, M + timedelta(days=d))
    assert wi.recovery is recovery
    if wi.phase in ("peak", "taper"):
        assert wi.recovery is False


# ---------------------------------------------------------------------------------------------------------
# §10.2 targets
# ---------------------------------------------------------------------------------------------------------


def test_weekly_target_per_phase() -> None:
    ctl = 50.0
    assert weekly_target(ctl, info("base")) == pytest.approx(7 * (50 + 24), abs=TOL)  # 518
    assert weekly_target(ctl, info("build")) == pytest.approx(7 * (50 + 30), abs=TOL)  # 560
    assert weekly_target(ctl, info("peak")) == pytest.approx(350.0, abs=TOL)
    assert weekly_target(ctl, info("base", recovery=True)) == pytest.approx(518 * 0.7, abs=TOL)  # 362.6
    assert weekly_target(ctl, info("build", recovery=True)) == pytest.approx(392.0, abs=TOL)
    assert weekly_target(ctl, info("taper", d=6), pre_taper_target=400.0) == pytest.approx(200.0, abs=TOL)
    # no pre-taper target: the peak formula stands in for it → 0.5 · 7 · 50
    assert weekly_target(ctl, info("taper", d=6)) == pytest.approx(175.0, abs=TOL)


def test_weekly_target_never_negative() -> None:
    assert weekly_target(-40.0, info("base")) == 0.0  # 7 · (−40 + 24) < 0
    assert weekly_target(-1.0, info("peak")) == 0.0
    assert weekly_target(0.0, info("taper"), pre_taper_target=-10.0) == 0.0
    assert weekly_target(0.0, info("base")) == pytest.approx(168.0, abs=TOL)


def test_ramp_cap_target() -> None:
    # 7 · (CTL + 6 / Q); Q = 1 − (41/42)^7 = 0.155223…, 6 / Q = 38.654…
    assert abs(Q - 0.155223) < 1e-6
    assert ramp_cap_target(0.0) == pytest.approx(42 / Q, abs=TOL)
    assert ramp_cap_target(50.0) == pytest.approx(350 + 42 / Q, abs=TOL)
    # the capped constant daily load raises CTL by exactly 6 in 7 days
    ctl = project_ctl(50.0, [ramp_cap_target(50.0) / 7] * 7)
    assert ctl[-1] - 50.0 == pytest.approx(6.0, abs=1e-9)


def test_cap_binds_for_a_steep_ramp(monkeypatch: pytest.MonkeyPatch) -> None:
    # With the built-in ramps (≤ 5 < 1/Q ≈ 6.44) the cap never binds; force it with ramp 10.
    assert weekly_target(50.0, info("build")) < ramp_cap_target(50.0)
    monkeypatch.setitem(season.RAMP, "build", 10.0)
    assert weekly_target(50.0, info("build")) == pytest.approx(ramp_cap_target(50.0), abs=TOL)
    # a recovery week scales first, then the cap: 0.7 · 7 · (50 + 60) = 539 < cap(50) ≈ 620.6 → 539
    assert weekly_target(50.0, info("build", recovery=True)) == pytest.approx(539.0, abs=TOL)


def test_split_targets() -> None:
    run, bike = split_targets(500.0, 0.6)
    assert (run, bike) == (pytest.approx(300.0), pytest.approx(200.0))
    assert split_targets(500.0, 1.0) == (500.0, 0.0)
    assert split_targets(500.0, 0.0) == (0.0, 500.0)
    assert split_targets(500.0, 1.5) == (500.0, 0.0)  # clamped


@pytest.mark.parametrize(
    ("split", "run28", "total28", "expected"),
    [
        (0.6, 100.0, 1000.0, 0.6),  # the athlete split wins
        (0.0, 100.0, 1000.0, 0.0),  # 0 is a valid split, not "null"
        (1.2, 0.0, 0.0, 1.0),  # clamped
        (-0.1, 0.0, 0.0, 0.0),
        (None, 300.0, 400.0, 0.75),  # 28-day run share of load_total
        (None, 300.0, 1000.0, 0.3),  # "other" load counts in the total (bike gets the rest)
        (None, 0.0, 0.0, 1.0),  # no load → 1.0
        (None, 0.0, 250.0, 0.0),
        (float("nan"), 50.0, 100.0, 0.5),  # NaN split treated as null
        (None, float("nan"), float("nan"), 1.0),
    ],
)
def test_run_share(split: float | None, run28: float, total28: float, expected: float) -> None:
    assert run_share(split, run28, total28) == pytest.approx(expected, abs=TOL)


# ---------------------------------------------------------------------------------------------------------
# §4 CTL recursion and ramp
# ---------------------------------------------------------------------------------------------------------


def test_project_ctl() -> None:
    # CTL[d] = CTL[d−1] + (L − CTL[d−1]) / 42, from CTL[−1] = ctl0
    assert project_ctl(0.0, [42.0, 0.0]) == pytest.approx([1.0, 1.0 - 1 / 42], abs=TOL)
    assert project_ctl(30.0, []) == []
    assert project_ctl(30.0, [30.0] * 5) == pytest.approx([30.0] * 5, abs=TOL)
    # 7 days of constant L close Q of the gap
    assert project_ctl(20.0, [62.0] * 7)[-1] == pytest.approx(20 + 42 * Q, abs=TOL)


def test_weekly_ramp() -> None:
    series = [float(i) for i in range(10)]
    ramp = weekly_ramp(series)
    assert len(ramp) == 10
    assert all(math.isnan(r) for r in ramp[:7])
    assert ramp[7:] == [7.0, 7.0, 7.0]
    assert weekly_ramp([]) == []


# ---------------------------------------------------------------------------------------------------------
# season_plan
# ---------------------------------------------------------------------------------------------------------


def test_season_plan_projection_and_split() -> None:
    race = M + timedelta(days=120)  # two base weeks: d = 120 (d // 7 = 17), 113 (16 → recovery)
    plan = season_plan(M, 2, 30.0, race, 0.6)
    assert [w.monday for w in plan] == [M, M + timedelta(days=7)]
    w0, w1 = plan
    assert isinstance(w0, WeekTarget)
    assert (w0.phase, w0.recovery, w0.days_to_race) == ("base", False, 120)
    assert w0.ctl_start == 30.0
    assert w0.target_load == pytest.approx(7 * 54, abs=TOL)  # 378
    assert (w0.run_target, w0.bike_target) == (pytest.approx(226.8), pytest.approx(151.2))
    # daily 54 for 7 days: CTL = 30 + 24 · Q
    assert w1.ctl_start == pytest.approx(30 + 24 * Q, abs=TOL)
    assert (w1.recovery, w1.days_to_race) == (True, 113)
    assert w1.target_load == pytest.approx(0.7 * 7 * (w1.ctl_start + 24), abs=TOL)


def test_season_plan_edge_inputs() -> None:
    assert season_plan(M, 0, 30.0, None, 1.0) == []
    with pytest.raises(ValueError, match="weeks"):
        season_plan(M, -1, 30.0, None, 1.0)
    with pytest.raises(ValueError, match="Monday"):
        season_plan(M + timedelta(days=2), 1, 30.0, None, 1.0)


def test_two_taper_weeks_both_half_of_pre_taper() -> None:
    # race on a Wednesday: weeks d = 16 (peak), 9 (taper), 2 (taper), then −5 (no-goal cycle)
    race = M + timedelta(days=16)
    plan = season_plan(M, 4, 40.0, race, 1.0)
    assert [w.phase for w in plan] == ["peak", "taper", "taper", "base"]
    assert [w.days_to_race for w in plan] == [16, 9, 2, None]
    peak = plan[0].target_load
    assert peak == pytest.approx(280.0, abs=TOL)  # 7 · 40
    assert plan[1].target_load == pytest.approx(140.0, abs=TOL)
    assert plan[2].target_load == pytest.approx(140.0, abs=TOL)  # not 70: no compounding
    assert plan[2].ctl_start < plan[1].ctl_start < plan[0].ctl_start + TOL
    # after the race: the no-goal cycle (k of M + 21 = 147, 147 % 4 = 3 → recovery)
    assert plan[3].recovery is True
    assert plan[3].target_load == pytest.approx(0.7 * 7 * (plan[3].ctl_start + 24), abs=TOL)


@pytest.mark.parametrize("start_offset", [0, 7])
def test_plan_starting_inside_the_taper(start_offset: int) -> None:
    # taper weeks d = 9 and 2; the pre-taper (peak) week is computed virtually with CTL_now → 7 · 40
    first = M + timedelta(days=start_offset)
    race = M + timedelta(days=9)  # M: d = 9, M + 7: d = 2, M − 7 (virtual): d = 16 → peak
    plan = season_plan(first, 2 - start_offset // 7, 40.0, race, 1.0)
    assert [w.phase for w in plan] == ["taper"] * len(plan)
    assert [w.target_load for w in plan] == pytest.approx([140.0] * len(plan), abs=TOL)


# ---------------------------------------------------------------------------------------------------------
# full simulated 16-week season
# ---------------------------------------------------------------------------------------------------------

# §10.3 default roles after the per-phase transforms (mon … sun)
PHASE_ROLES = {
    "base": ("rest", "q1", "easy", "easy", "easy", "long", "easy"),
    "build": ("rest", "q1", "easy", "q2", "easy", "long", "easy"),
    "peak": ("rest", "q1", "easy", "q2", "rest", "long", "easy"),
    "taper": ("rest", "q1", "easy", "q2", "easy", "easy", "easy"),
}


def daily_pattern(target: float, phase: str) -> list[float]:
    """Split a weekly target over the days: rest 0, easy 1, long 2, quality 1.25 (sums to target)."""
    w = [WEIGHTS[r] for r in PHASE_ROLES[phase]]
    return [target * x / sum(w) for x in w]


def test_full_16_week_season() -> None:
    race = M + timedelta(weeks=15, days=6)  # the Sunday of week 16 → d = 111 on M
    plan = season_plan(M, 16, 30.0, race, 0.6)
    phases = [w.phase for w in plan]
    assert phases == ["base"] * 4 + ["build"] * 9 + ["peak"] * 2 + ["taper"]
    assert [w.days_to_race for w in plan] == [111 - 7 * i for i in range(16)]
    # recovery weeks at d // 7 = 12 (d = 90, base), 8 (62), 4 (34)
    assert [i for i, w in enumerate(plan) if w.recovery] == [3, 7, 11]
    assert plan[15].target_load == pytest.approx(0.5 * plan[14].target_load, abs=TOL)

    loads: list[float] = []
    for w in plan:
        pattern = daily_pattern(w.target_load, w.phase)
        assert sum(pattern) == pytest.approx(w.target_load, abs=1e-9)
        assert w.run_target + w.bike_target == pytest.approx(w.target_load, abs=1e-9)
        loads.extend(pattern)
    ctl = [30.0, *project_ctl(30.0, loads)]  # ctl[0] = the day before M
    ramps = [r for r in weekly_ramp(ctl) if not math.isnan(r)]
    assert len(ramps) == 16 * 7 + 1 - 7
    assert max(ramps) <= RAMP_CAP

    week_end = [ctl[7 * (i + 1)] for i in range(16)]  # CTL on each Sunday
    week_start = [ctl[7 * i] for i in range(16)]  # CTL on the day before each Monday
    for i, w in enumerate(plan):
        if w.phase in ("base", "build") and not w.recovery:
            assert week_end[i] > week_start[i], f"week {i} ({w.phase}) should raise CTL"
    last_build = max(i for i, p in enumerate(phases) if p == "build")
    assert week_end[last_build] > 30.0 + 30  # ≈ 3.7 · 3 + 4.7 · 8 + small recovery changes
    assert week_end[15] < week_start[15]  # the taper sheds fitness
