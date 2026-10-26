"""Coach "Kondícia" – METRICS §11 rules with known answers (pure, no DB)."""

from datetime import date, timedelta

import pytest

from training.coach import fitness as f
from training.coach.workout import estimated_load, total_duration_s

MON = date(2026, 10, 26)  # a Monday
WEEK = [MON + timedelta(days=i) for i in range(7)]
ALL = frozenset(WEEK)


def week(no: int = 2, target_min: float = 150.0, test: bool = False) -> f.WeekLoad:
    return f.WeekLoad(no, target_min * 60, target_min * 60, None, no in f.RECOVERY_WEEKS, test)


def ctx(day: date, readiness: float | None, open_items: str = "kde", **kw) -> f.FitnessContext:
    return f.FitnessContext(
        day=day,
        readiness=readiness,
        available=kw.pop("available", ALL),
        open_items=frozenset(open_items),
        hard_yesterday=kw.pop("hard_yesterday", None),
        ran_yesterday=kw.pop("ran_yesterday", False),
        week=kw.pop("week", week()),
        **kw,
    )


# --- colour, brake, weekly time ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("p", "expected"),
    [
        (70.0, "green"),
        (69.99, "yellow"),
        (45.0, "yellow"),
        (44.9, "red"),
        (None, "yellow"),
        (float("nan"), "yellow"),
    ],
)
def test_colour(p, expected):
    assert f.color(p) == expected


def test_brake_order_and_missing_inputs():
    assert f.brake(None, None, None) is None
    assert f.brake(60, 4 * 3600, 1.2) is None
    assert f.brake(54.9, None, None) == "hold"
    assert f.brake(None, 5 * 3600 + 1, None) == "hold"
    assert f.brake(None, None, 1.31) == "hold"
    assert f.brake(44, 0, 0.9) == "cut"


def test_first_base_is_the_median_but_at_least_90_minutes():
    assert f.first_base([]) == 5400
    assert f.first_base([3000, 9000, 6000, 12000]) == 7500  # median of 4
    assert f.first_base([1000, 2000, 3000]) == 5400


def test_progression_recovery_does_not_reset_the_base():
    w1 = f.week_load(1, None, None, 6000)
    w2 = f.week_load(2, w1.base_s, None, 6000)
    w3 = f.week_load(3, w2.base_s, "hold", 6000)
    w4 = f.week_load(4, w3.base_s, None, 6000)
    w5 = f.week_load(5, w4.base_s, "cut", 6000)
    assert w1.target_s == 6000 and w2.base_s == pytest.approx(6420)
    assert w3.base_s == pytest.approx(6420) and w3.brake == "hold"
    assert (
        w4.recovery
        and w4.base_s == pytest.approx(6420 * 1.07)
        and w4.target_s == pytest.approx(6420 * 1.07 * 0.7)
    )
    assert w5.base_s == pytest.approx(6420 * 1.07 * 0.85)  # grows from week 4's base, not its target
    assert f.week_load(6, w5.base_s, None, 6000).test and f.week_load(12, 6000, None, 6000).test


def test_session_minutes_split_round_and_clamp():
    # T = 150 min: D 60, K 45, Ľ 45
    assert [f.session_minutes(9000, s, weekend=True) for s in ("d", "k", "e")] == [60, 45, 45]
    assert f.session_minutes(4 * 3600, "d", weekend=True) == 95  # 96 → 95
    assert f.session_minutes(4 * 3600, "d", weekend=False) == 60  # weekday cap
    assert f.session_minutes(5400, "e", weekend=False) == 25  # 27 → 25
    assert f.session_minutes(3000, "k", weekend=False) == 35  # clamp up
    assert f.session_minutes(6 * 3600, "e", weekend=False) == 60  # clamp down


# --- workouts ---------------------------------------------------------------------------------------------


def test_quality_rotation_and_sizes():
    threshold = f.quality_run(45, week_no=1)  # 15 + 20 + 10 → 2 reps → clamped to 3
    assert threshold.key == "fit_threshold" and threshold.name == "Prahové intervaly 3×6 min"
    vo2 = f.quality_run(60, week_no=2)  # main 35 → 5 reps
    assert vo2.name == "VO2 intervaly 5×3 min"
    tempo = f.quality_run(60, week_no=3)  # main 35 → 25 max
    assert tempo.name == "Tempo 25 min"
    hills = f.quality_run(40, week_no=8)  # warm-up 10, main 20 → 8 reps
    assert hills.name == "Kopce 8×60 s" and total_duration_s(hills) == 600 + 8 * 150 + 600
    assert all(w.slot == "k" for w in (threshold, vo2, tempo, hills))


def test_mild_check_and_easy_workouts():
    mild = f.mild_quality_run(45)  # main 20 → 20
    assert mild.name == "Mierne tempo 20 min" and mild.steps[1].target.zone == 3
    check = f.check_run()
    assert total_duration_s(check) == 55 * 60 and check.steps[1].target.kind == "open"
    easy = f.easy_run(40)
    assert easy.slot == "e" and estimated_load(easy) == pytest.approx(2400 * 0.65**2 / 36)


# --- daily rules ------------------------------------------------------------------------------------------


def test_rule1_red_day_is_rest_even_when_everything_is_open():
    d = f.decide(ctx(WEEK[5], 40, "kde"))
    assert (d.rule, d.workout.sport) == (1, "rest") and "červená" in d.reason


def test_rule2_after_a_hard_day_only_easy():
    d = f.decide(ctx(WEEK[1], 80, "ke", hard_yesterday="dlhší beh"))
    assert (d.rule, d.workout.slot) == (2, "e") and "Včera dlhší beh" in d.reason
    d = f.decide(ctx(WEEK[1], 80, "k", hard_yesterday="kvalitný tréning"))
    assert (d.rule, d.workout.sport) == (2, "rest")


def test_rule3_green_day_quality_and_check_in_test_weeks():
    d = f.decide(ctx(WEEK[1], 75, "kde"))
    assert (d.rule, d.workout.slot) == (3, "k") and d.workout.key == "fit_vo2"  # week 2
    d = f.decide(ctx(WEEK[1], 75, "kde", week=week(6, test=True)))
    assert d.workout.key == "fit_check" and "Testovací týždeň" in d.reason


def test_rule4_long_on_the_weekend_or_when_needed():
    d = f.decide(ctx(WEEK[5], 60, "kde"))  # Saturday, yellow
    assert (d.rule, d.workout.slot) == (4, "d") and d.workout.param == 60
    d = f.decide(ctx(WEEK[1], 60, "kde", available=frozenset(WEEK[1:4])))  # Tue: 3 days left for 3 runs
    assert (d.rule, d.workout.slot) == (4, "d")


def test_rule5_easy_spreads_runs():
    d = f.decide(ctx(WEEK[1], 60, "kde"))  # Tuesday, yellow, rested yesterday
    assert (d.rule, d.workout.slot) == (5, "e")
    d = f.decide(ctx(WEEK[1], 60, "kde", ran_yesterday=True))
    assert (d.rule, d.workout.sport) == (7, "rest") and "rozložia" in d.reason


def test_rule6_mild_quality_when_no_green_day_comes():
    d = f.decide(ctx(WEEK[6], 60, "k", ran_yesterday=True))  # Sunday, only K left
    assert (d.rule, d.workout.key) == (6, "fit_tempo_mild")


def test_week_done_and_unavailable_days_rest():
    d = f.decide(ctx(WEEK[3], 90, ""))
    assert (d.rule, d.workout.sport) == (7, "rest") and "hotový" in d.reason
    d = f.decide(ctx(WEEK[2], 90, "kde", available=frozenset(WEEK[3:])))
    assert (d.rule, d.workout.sport) == (0, "rest")


def test_must_counts_available_days_from_today():
    assert f.must_train(ctx(WEEK[4], 60, "kde"))  # Fri, Sat, Sun for 3 runs
    assert not f.must_train(ctx(WEEK[3], 60, "kde"))
    assert not f.must_train(ctx(WEEK[6], 60, ""))


def test_bike_override_and_reason_shows_the_menu():
    d = f.decide(ctx(WEEK[2], 60, "kd", sport_override="bike"))
    assert d.workout.sport == "bike" and d.workout.key == "fit_ride"
    assert "Týždeň 2/12: K – D – Ľ ✓." in d.reason
