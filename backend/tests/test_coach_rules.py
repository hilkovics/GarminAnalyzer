"""Daily decision – METRICS §10.4 (incl. the 2026-09-29 phase-6 clarification), rules 1–4.

Reference week: Monday 2026-10-05, `cycle_k = (2026-10-05 − 2024-01-01).days // 7 = 1008 // 7 = 144`
(even → Build q2 = VO2; 144 % 3 = 0 → Base q1 = tempo). Default roles: mon rest, tue q1, wed easy, thu q2,
fri easy, sat long, sun easy.

Hand-computed §10.6 loads (IF² · s / 36): Z1 0.25·s/36, Z2 0.4225·s/36, Z3 0.6889·s/36, Z4 0.9604·s/36,
Z5 1.21·s/36.
- quality frame: warm-up 900 s Z2 = 10.5625, cool-down 600 s Z1 = 4.1667 → 14.7292
- threshold rep (360 s Z4 + 120 s Z1) = 9.604 + 0.8333 = 10.4373 → 4 reps 56.478, 5 reps 66.916, 6 reps 77.353
- run VO2 rep (180 s Z5 + 120 s Z1) = 6.05 + 0.8333 = 6.8833
- easy run per minute = 60 · 0.4225 / 36 = 0.70417 → 65 min 45.771, 70 min 49.292, 75 min 52.813
"""

import dataclasses
from datetime import date, timedelta

import pytest

from training.coach import library, rules
from training.coach.rules import (
    ACWR_DANGER,
    MONOTONY_HIGH,
    QUALITY_IF,
    READINESS_RED,
    RULE2_ORDER,
    SLOT_WEIGHTS,
    TSB_FLOOR,
    DayContext,
    Decision,
    DoneSession,
    decide,
)
from training.coach.season import week_info
from training.coach.template import WEEKDAYS, week_roles
from training.coach.workout import HrZoneTarget, RepeatStep, estimated_load

MON = date(2026, 10, 5)
TUE, WED, THU, FRI, SAT, SUN = (MON + timedelta(days=i) for i in range(1, 7))
RACE = {  # race dates giving the phase of the reference week (§10.1 clarified, d = days Monday → race)
    "base": None,  # no goal: base, k = 144, 144 % 4 = 0 → not a recovery week
    "build": MON + timedelta(days=50),  # d = 50, 50 // 7 = 7 → not a recovery week
    "peak": MON + timedelta(days=14),
    "taper": MON + timedelta(days=6),
}


def ctx_for(
    day: date,
    phase: str = "build",
    preferred_days: dict | None = None,
    **overrides: object,
) -> DayContext:
    """A calm default context: readiness 70, TSB −5, ACWR 1.0, monotony 1.2, target 400 all run.

    Every day Mon … D−1 except the template rest days had an activity.
    """
    info = week_info(MON, RACE[phase])
    assert info.phase == phase
    roles = week_roles(phase, preferred_days)
    days_before = [MON + timedelta(days=i) for i in range((day - MON).days)]
    active = frozenset(d for d in days_before if roles[WEEKDAYS[d.weekday()]].role != "rest")
    base: dict[str, object] = {
        "day": day,
        "info": info,
        "roles": roles,
        "weekly_target": 400.0,
        "run_target": 400.0,
        "bike_target": 0.0,
        "load_done_week": 0.0,
        "run_load_done_week": 0.0,
        "bike_load_done_week": 0.0,
        "active_days_week": active,
        "done": (),
        "yesterday_max_if": None,
        "readiness": 70.0,
        "tsb": -5.0,
        "acwr_prev": 1.0,
        "monotony_prev": 1.2,
        "goal_sport": None if phase == "base" else "run",
        "race_zone": 4,
    }
    base.update(overrides)
    return DayContext(**base)  # type: ignore[arg-type]


def done(day: date, key: str, slot: str | None, sport: str = "run") -> DoneSession:
    return DoneSession(date=day, sport=sport, key=key, slot=slot)


def summary(d: Decision) -> tuple[str, str, str, int | None, int]:
    return d.workout.sport, d.workout.key, d.slot, d.workout.param, d.rule


# ---------------------------------------------------------------------------------------------------------
# constants
# ---------------------------------------------------------------------------------------------------------


def test_constants() -> None:
    assert (READINESS_RED, ACWR_DANGER, TSB_FLOOR, MONOTONY_HIGH, QUALITY_IF) == (45, 1.5, -30, 2.0, 0.85)
    assert SLOT_WEIGHTS == {"long": 2.0, "q1": 1.25, "q2": 1.25, "easy": 1.0}
    assert RULE2_ORDER == ("long", "q1", "q2", "easy")


# ---------------------------------------------------------------------------------------------------------
# rule 1
# ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "trigger", "no_trigger"),
    [("readiness", 44.9, 45.0), ("acwr_prev", 1.51, 1.5), ("tsb", -30.1, -30.0)],
)
def test_rule1_each_trigger_strict(field: str, trigger: float, no_trigger: float) -> None:
    hit = decide(ctx_for(TUE, **{field: trigger}))
    miss = decide(ctx_for(TUE, **{field: no_trigger}))
    assert hit.rule == 1
    assert miss.rule == 3 and miss.workout.key == "threshold"


@pytest.mark.parametrize(
    ("field", "label"),
    [("readiness", "pripravenosť"), ("acwr_prev", "ACWR"), ("tsb", "TSB"), ("monotony_prev", "monotónnosť")],
)
def test_null_input_never_triggers_and_reason_names_it(field: str, label: str) -> None:
    d = decide(ctx_for(TUE, **{field: None}))
    assert (d.rule, d.workout.key, d.slot) == (3, "threshold", "q1")
    assert d.reason.endswith(f"Chýba: {label}.")


def test_nan_counts_as_missing() -> None:
    d = decide(ctx_for(TUE, readiness=float("nan"), acwr_prev=None))
    assert d.rule == 3
    assert d.reason.endswith("Chýba: pripravenosť, ACWR.")


def test_rule1_rest_while_quota_not_used() -> None:
    # Tuesday: Monday (the template rest day) had an activity → 0 rest days used < quota 1 → rest.
    ctx = ctx_for(TUE, readiness=38.0, active_days_week=frozenset({MON}))
    d = decide(ctx)
    assert (d.workout.sport, d.workout.key, d.slot, d.rule) == ("rest", "rest", "rest", 1)
    assert d.target_load is None
    assert d.workout.steps == [] and d.workout.slot is None
    assert d.reason == "Pripravenosť 38 < 45 → voľno (týždenná kvóta voľna ešte nevyčerpaná)."


def test_rule1_recovery_when_quota_used() -> None:
    # Wednesday: Monday rested → 1 rest day used = quota 1 → 40 min Z1 in today's sport (easy → run).
    d = decide(ctx_for(WED, acwr_prev=1.62))
    assert summary(d) == ("run", "recovery", "recovery", 40, 1)
    assert d.target_load is None and d.workout.slot is None
    assert estimated_load(d.workout) == pytest.approx(2400 * 0.25 / 36)
    assert d.reason == "ACWR 1.62 > 1.5 → regenerácia 40 min Z1 (týždenná kvóta voľna vyčerpaná)."


def test_rule1_lists_every_trigger() -> None:
    d = decide(ctx_for(WED, readiness=40.0, acwr_prev=1.6, tsb=-32.4))
    assert d.reason.startswith("Pripravenosť 40 < 45, ACWR 1.6 > 1.5, TSB -32.4 < -30 → regenerácia")


def test_rule1_wins_over_rule2_and_rule3() -> None:
    ctx = ctx_for(WED, tsb=-31.0, monotony_prev=2.5, done=(done(MON - timedelta(days=2), "easy", "easy"),))
    assert decide(ctx).rule == 1


def test_rule1_peak_week_has_two_rest_days_of_quota() -> None:
    # Peak: the easy Friday before the long Saturday becomes rest → quota 2; Monday rested (1) < 2 → rest.
    d = decide(ctx_for(WED, phase="peak", readiness=30.0))
    assert (d.slot, d.rule) == ("rest", 1)


def test_rule1_on_template_rest_day_stays_rest_even_with_quota_used() -> None:
    # Custom week with Sunday rest: Mon + Thu rested already (≥ quota 2) – today's planned rest stays rest.
    pref = {"sun": "rest"}
    ctx = ctx_for(SUN, preferred_days=pref, readiness=30.0, active_days_week=frozenset({TUE, WED, FRI, SAT}))
    d = decide(ctx)
    assert (d.slot, d.rule) == ("rest", 1)
    assert d.reason == "Pripravenosť 30 < 45 → voľno (podľa plánu deň voľna)."


def test_rule1_recovery_sport_follows_today_slot_and_override() -> None:
    pref = {"wed": {"role": "easy", "sport": "bike"}}
    assert decide(ctx_for(WED, preferred_days=pref, readiness=20.0)).workout.sport == "bike"
    d = decide(ctx_for(WED, readiness=20.0, sport_override="bike"))
    assert (d.workout.sport, d.workout.key, d.slot) == ("bike", "recovery", "recovery")


# ---------------------------------------------------------------------------------------------------------
# rule 2
# ---------------------------------------------------------------------------------------------------------


def test_rule2_swaps_a_key_done_in_last_7_days() -> None:
    # Base Tuesday q1 = tempo; tempo was done last Thursday → first not-done key in order long, q1, q2, easy.
    ctx = ctx_for(TUE, phase="base", monotony_prev=2.3, done=(done(MON - timedelta(days=4), "tempo", "q1"),))
    d = decide(ctx)
    assert (d.workout.key, d.slot, d.rule, d.workout.slot) == ("long", "long", 2, "long")
    assert d.reason.startswith(
        "Monotónnosť 2.3 > 2.0 → Dlhý beh namiesto Tempo (tréning Tempo bol v posledných 7 dňoch). Base,"
    )


def test_rule2_skips_every_done_key_in_order() -> None:
    recent = (done(MON - timedelta(days=4), "tempo", "q1"), done(MON - timedelta(days=2), "long", "long"))
    d = decide(ctx_for(TUE, phase="base", monotony_prev=2.3, done=recent))
    assert (d.workout.key, d.slot, d.rule) == ("easy", "easy", 2)


def test_rule2_no_alternative_keeps_today() -> None:
    recent = (
        done(MON - timedelta(days=5), "tempo", "q1"),
        done(MON - timedelta(days=4), "easy", "easy"),
        done(MON - timedelta(days=2), "long", "long"),
    )
    d = decide(ctx_for(TUE, phase="base", monotony_prev=2.3, done=recent))
    assert (d.workout.key, d.slot, d.rule) == ("tempo", "q1", 2)
    assert d.reason.startswith(
        "Monotónnosť 2.3 > 2.0, všetky typy tréningov týždňa boli v posledných 7 dňoch →"
    )


def test_rule2_key_not_done_keeps_today_and_ignores_older_sessions() -> None:
    eight_days_ago = done(TUE - timedelta(days=8), "tempo", "q1")
    d = decide(ctx_for(TUE, phase="base", monotony_prev=2.3, done=(eight_days_ago,)))
    assert (d.workout.key, d.slot, d.rule) == ("tempo", "q1", 2)


def test_rule2_same_key_other_sport_is_a_different_type() -> None:
    d = decide(ctx_for(TUE, phase="base", monotony_prev=2.3, done=(done(MON, "tempo", "q1", "bike"),)))
    assert (d.workout.key, d.rule) == ("tempo", 2)


def test_rule2_threshold_is_strict_and_rest_day_stays_rest() -> None:
    recent = (done(MON - timedelta(days=4), "tempo", "q1"),)
    assert decide(ctx_for(TUE, phase="base", monotony_prev=2.0, done=recent)).rule == 3
    d = decide(ctx_for(MON, phase="base", monotony_prev=2.5))
    assert (d.slot, d.rule) == ("rest", 3)


# ---------------------------------------------------------------------------------------------------------
# rule 3
# ---------------------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("day", "done_sessions", "key", "slot"),
    [
        (TUE, (), "threshold", "q1"),
        (THU, (done(TUE, "threshold", "q1"),), "vo2", "q2"),
        (SAT, (done(TUE, "threshold", "q1"), done(THU, "vo2", "q2")), "long_build", "long"),
        (WED, (done(TUE, "threshold", "q1"),), "easy", "easy"),
    ],
)
def test_rule3_today_role(day: date, done_sessions: tuple, key: str, slot: str) -> None:
    d = decide(ctx_for(day, done=done_sessions))
    assert (d.workout.key, d.slot, d.rule, d.workout.slot) == (key, slot, 3, slot)


def test_rule3_rest_day() -> None:
    d = decide(ctx_for(MON))
    assert (d.workout.sport, d.workout.key, d.slot, d.rule) == ("rest", "rest", "rest", 3)
    assert d.target_load is None
    assert d.reason == "Build: podľa plánu deň voľna."


def test_rule3_missed_quality_moves_to_easy_day() -> None:
    d = decide(ctx_for(WED))  # Tuesday's q1 not done
    assert (d.workout.key, d.slot, d.rule) == ("threshold", "q1", 3)
    assert d.reason.startswith("Vynechaný kvalitný tréning 1 (ut) → dnes. Build, týždeň 0 % splnený:")


def test_rule3_takes_the_earliest_missed_slot() -> None:
    assert decide(ctx_for(FRI)).workout.key == "threshold"  # q1 (Tue) and q2 (Thu) missed → q1
    d = decide(ctx_for(FRI, done=(done(WED, "threshold", "q1"),)))  # q1 made up on Wednesday
    assert (d.workout.key, d.slot) == ("vo2", "q2")


def test_rule3_missed_long_moves_even_after_a_hard_day() -> None:
    week = (done(TUE, "threshold", "q1"), done(THU, "vo2", "q2"))
    d = decide(ctx_for(SUN, done=week, yesterday_max_if=0.95))
    assert (d.workout.key, d.slot) == ("long_build", "long")


def test_rule3_quality_after_done_quality_yesterday_becomes_easy() -> None:
    # Tuesday's q1 was made up on Wednesday → Thursday's q2 turns easy.
    d = decide(ctx_for(THU, done=(done(WED, "threshold", "q1"),)))
    assert (d.workout.key, d.slot, d.rule) == ("easy", "easy", 3)
    assert d.reason.startswith("Včera kvalitný tréning → ľahký deň. Build,")


@pytest.mark.parametrize(("max_if", "key"), [(0.85, "easy"), (0.91, "easy"), (0.84, "vo2")])
def test_rule3_quality_after_hard_activity_yesterday(max_if: float, key: str) -> None:
    d = decide(ctx_for(THU, done=(done(TUE, "threshold", "q1"),), yesterday_max_if=max_if))
    assert d.workout.key == key
    if key == "easy":
        assert d.reason.startswith(f"Včera kvalitný tréning (IF {max_if:.2f} ≥ 0.85) → ľahký deň.")


def test_rule3_moved_quality_is_downgraded_too() -> None:
    d = decide(ctx_for(WED, yesterday_max_if=0.9))  # q1 missed on Tuesday, but Tuesday was hard
    assert (d.workout.key, d.slot) == ("easy", "easy")


# ---------------------------------------------------------------------------------------------------------
# sport choice
# ---------------------------------------------------------------------------------------------------------


def test_sport_override_changes_sport_but_not_a_rest_day() -> None:
    d = decide(ctx_for(TUE, sport_override="bike"))
    assert (d.workout.sport, d.workout.key, d.slot) == ("bike", "over_unders", "q1")
    assert decide(ctx_for(MON, sport_override="bike")).slot == "rest"


def test_invalid_sport_override_raises() -> None:
    with pytest.raises(ValueError, match="sport_override"):
        decide(ctx_for(TUE, sport_override="swim"))


def test_bike_slot_from_preferred_days() -> None:
    pref = {"sat": {"role": "long", "sport": "bike"}}
    week = (done(TUE, "threshold", "q1"), done(THU, "vo2", "q2"))
    d = decide(ctx_for(SAT, preferred_days=pref, done=week, weekly_target=600.0))
    assert (d.workout.sport, d.workout.key, d.slot) == ("bike", "long_ride", "long")


def test_easy_day_uses_sport_with_larger_remaining_target() -> None:
    ctx = ctx_for(
        WED,
        done=(done(TUE, "threshold", "q1"),),
        run_target=240.0,
        bike_target=160.0,
        run_load_done_week=100.0,  # remaining run 140 < remaining bike 160
    )
    assert decide(ctx).workout.key == "endurance"
    assert decide(dataclasses.replace(ctx, run_load_done_week=80.0)).workout.sport == "run"  # 160 = 160 → run


# ---------------------------------------------------------------------------------------------------------
# rule 4
# ---------------------------------------------------------------------------------------------------------


def test_rule4_hand_computed_quality_target() -> None:
    # Tuesday, 400 remaining; weights tue 1.25 + wed 1 + thu 1.25 + fri 1 + sat 2 + sun 1 = 7.5
    # → target 400 · 1.25 / 7.5 = 66.667; threshold 5 reps = 66.916 (4: 56.478, 6: 77.353) → 5.
    d = decide(ctx_for(TUE))
    assert d.target_load == pytest.approx(400 * 1.25 / 7.5)
    assert d.workout.param == 5
    assert estimated_load(d.workout) == pytest.approx(14.7292 + 5 * 10.4373, abs=1e-3)
    assert d.reason == "Build, týždeň 0 % splnený: Prahové intervaly 5×6 min, odhad 67 bodov (cieľ dňa 67)."


def test_rule4_hand_computed_easy_target_after_load_done() -> None:
    # Friday, 200 of 400 done → remaining 200; weights fri 1 + sat 2 + sun 1 = 4 → target 50;
    # easy 70 min = 49.292 (65: 45.771, 75: 52.813) → 70.
    week = (done(TUE, "threshold", "q1"), done(THU, "vo2", "q2"))
    d = decide(ctx_for(FRI, done=week, load_done_week=200.0, run_load_done_week=200.0))
    assert d.target_load == pytest.approx(50.0)
    assert (d.workout.key, d.workout.param) == ("easy", 70)
    assert d.reason == "Build, týždeň 50 % splnený: Ľahký beh 70 min, odhad 49 bodov (cieľ dňa 50)."


def test_rule4_future_rest_days_carry_no_weight() -> None:
    # Custom week, Sunday rest: Friday weights fri 1 + sat 2 = 3 → target 300 / 3 = 100 → easy max 75 min.
    week = (done(TUE, "threshold", "q1"), done(THU, "vo2", "q2"))
    d = decide(ctx_for(FRI, preferred_days={"sun": "rest"}, done=week, load_done_week=100.0))
    assert d.target_load == pytest.approx(100.0)
    assert d.workout.param == 75


def test_rule4_nothing_remaining_gives_min_param() -> None:
    d = decide(ctx_for(TUE, load_done_week=500.0))
    assert d.target_load == 0.0
    assert d.workout.param == library.param_values("run", "threshold")[0] == 4


def test_rule4_uses_race_zone() -> None:
    d = decide(ctx_for(TUE, phase="peak", race_zone=5))
    assert d.workout.key == "race_pace"
    repeat = next(s for s in d.workout.steps if isinstance(s, RepeatStep))
    assert repeat.steps[0].target == HrZoneTarget(zone=5)


# ---------------------------------------------------------------------------------------------------------
# taper, acceptance, determinism
# ---------------------------------------------------------------------------------------------------------


def test_taper_week_keys_from_roles() -> None:
    assert decide(ctx_for(TUE, phase="taper", weekly_target=150.0)).workout.key == "race_pace_short"
    week = (done(TUE, "race_pace_short", "q1"),)
    assert decide(ctx_for(THU, phase="taper", done=week)).workout.key == "strides"
    d = decide(ctx_for(SAT, phase="taper", done=(*week, done(THU, "strides", "q2"))))
    assert (d.workout.key, d.slot) == ("easy", "easy")  # Taper: long → easy


@pytest.mark.parametrize(("field", "good", "bad"), [("readiness", 80.0, 40.0), ("acwr_prev", 1.0, 1.6)])
def test_acceptance_decision_changes_with_readiness_and_acwr(field: str, good: float, bad: float) -> None:
    ok = decide(ctx_for(THU, done=(done(TUE, "threshold", "q1"),), **{field: good}))
    tired = decide(ctx_for(THU, done=(done(TUE, "threshold", "q1"),), **{field: bad}))
    assert (ok.workout.key, ok.rule) == ("vo2", 3)
    assert (tired.workout.key, tired.rule) == ("recovery", 1)
    assert ok.reason != tired.reason


def test_decide_is_deterministic() -> None:
    ctx = ctx_for(FRI, monotony_prev=2.4, done=(done(TUE, "threshold", "q1"),))
    assert decide(ctx) == decide(ctx)


def simulate_week(phase: str, weekly_target: float, **kw: object) -> list[Decision]:
    """Mon–Sun, each day's estimated load fed back as done load / DoneSession / active day."""
    decisions: list[Decision] = []
    load, sessions, active = 0.0, (), frozenset()
    for i in range(7):
        day = MON + timedelta(days=i)
        ctx = ctx_for(
            day,
            phase=phase,
            weekly_target=weekly_target,
            run_target=weekly_target,
            load_done_week=load,
            run_load_done_week=load,
            active_days_week=active,
            done=sessions,
            **kw,
        )
        d = decide(ctx)
        decisions.append(d)
        if d.workout.sport != "rest":
            load += estimated_load(d.workout)
            sessions = (*sessions, done(day, d.workout.key, d.workout.slot, d.workout.sport))
            active = active | {day}
    return decisions


@pytest.mark.parametrize(("phase", "target"), [("build", 350.0), ("base", 300.0), ("peak", 280.0)])
def test_simulated_week_lands_within_15_percent(phase: str, target: float) -> None:
    decisions = simulate_week(phase, target)
    total = sum(estimated_load(d.workout) for d in decisions)
    assert abs(total - target) <= 0.15 * target
    assert decisions[0].slot == "rest"
    assert all(d.rule == 3 for d in decisions)


def test_simulated_build_week_sequence() -> None:
    # Tue: 350 · 1.25 / 7.5 = 58.3 → threshold 4 (56.478); Wed: 293.52 / 6.25 = 46.96 → easy 65 (45.771);
    # Thu: 247.75 · 1.25 / 5.25 = 58.99 → VO2 6 (56.029); Fri: 191.72 / 4 = 47.93 → easy 70 (49.292);
    # Sat: 142.43 · 2 / 3 = 94.95 → long 120 (100 min Z2 70.417 + 20 min Z3 22.963 = 93.380);
    # Sun: 49.05 → easy 70 (49.292). Total 350.242 for a 350 target.
    decisions = simulate_week("build", 350.0)
    got = [(d.workout.key, d.workout.param) for d in decisions]
    assert got == [
        ("rest", None),
        ("threshold", 4),
        ("easy", 65),
        ("vo2", 6),
        ("easy", 70),
        ("long_build", 120),
        ("easy", 70),
    ]
    assert sum(estimated_load(d.workout) for d in decisions) == pytest.approx(350.242, abs=0.01)


def test_simulated_week_high_target_is_capped_by_library_ranges() -> None:
    # Documented limit: the §10.7 ranges cap a default Build run week at ≈ 420 points
    # (threshold 6, easy 75, VO2 8, easy 75, long 150, easy 75), so a 700 target cannot be met.
    decisions = simulate_week("build", 700.0)
    total = sum(estimated_load(d.workout) for d in decisions)
    assert total < 0.85 * 700.0
    assert all(
        d.workout.param == library.param_values(d.workout.sport, d.workout.key)[-1]
        for d in decisions
        if d.workout.sport != "rest"
    )


def test_module_exports() -> None:
    assert rules.decide is decide
