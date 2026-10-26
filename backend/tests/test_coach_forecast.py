"""Predictions (METRICS §11.5) with known answers: sleep effect, morning note, 7-day outlook (pure)."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from training.analysis.readiness import readiness
from training.coach import forecast as fc

TODAY = date(2026, 10, 26)  # a Monday


def dataset(n: int, slope: float, *, noise: float = 0.01, seed: int = 1) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    sleep_h = rng.uniform(5.0, 9.0, n)
    tsb = rng.uniform(-20.0, 10.0, n)
    pace = 3.0 + slope * sleep_h + 0.01 * tsb + rng.normal(0.0, noise, n)
    return pd.DataFrame({"pace_at_ref_hr_day": pace, "sleep_s_lag0": sleep_h * 3600, "tsb": tsb})


def test_sleep_effect_recovers_a_known_slope():
    effect = fc.sleep_effect(dataset(60, 0.05), n_boot=300)
    assert effect.status == fc.RELIABLE and effect.n == 60
    assert effect.slope == pytest.approx(0.05, abs=0.005)
    assert effect.ci_low < 0.05 < effect.ci_high
    assert effect.sleep_typ_s == pytest.approx(np.median(dataset(60, 0.05)["sleep_s_lag0"]))


def test_sleep_effect_without_a_relation_or_with_few_rows():
    assert fc.sleep_effect(dataset(60, 0.0, noise=0.2), n_boot=300).status == fc.UNCERTAIN
    few = fc.sleep_effect(dataset(29, 0.05))
    assert (few.status, few.n, few.slope) == (fc.INSUFFICIENT, 29, None)
    gaps = dataset(40, 0.05)
    gaps.loc[:15, "tsb"] = None  # rows without TSB do not count
    assert fc.sleep_effect(gaps).status == fc.INSUFFICIENT


def test_collinear_inputs_give_no_slope():
    frame = dataset(40, 0.05)
    frame["tsb"] = frame["sleep_s_lag0"] / 3600 * 2.0
    effect = fc.sleep_effect(frame, n_boot=50)
    assert effect.status == fc.UNCERTAIN and effect.slope is None


EFFECT = fc.SleepEffect(fc.RELIABLE, 50, 0.05, 0.02, 0.08, 7 * 3600.0, 3.0)


def test_morning_note():
    note = fc.sleep_note(EFFECT, 5 * 3600.0)  # Δv = −0.1 → 1000/2.9 − 1000/3 = 11.49 s/km slower
    assert note is not None and note.delta_s_per_km == 11
    assert note.text == (
        "Po 5:00 spánku (−2:00 oproti zvyčajným 7:00) býva tvoje tempo pri rovnakom tepe o ~11 s/km "
        "pomalšie – drž sa tepu, nie tempa."
    )
    faster = fc.sleep_note(EFFECT, 9 * 3600.0)
    assert faster is not None and faster.delta_s_per_km == -11 and faster.text.endswith("ísť ľahšie.")
    assert fc.sleep_note(EFFECT, 7.3 * 3600.0) is None  # 1.7 s/km < 3
    assert fc.sleep_note(EFFECT, None) is None
    uncertain = fc.SleepEffect(fc.UNCERTAIN, 50, 0.05, -0.01, 0.08, 7 * 3600.0, 3.0)
    assert fc.sleep_note(uncertain, 5 * 3600.0) is None


def test_typical_wellness_and_load_use_the_same_weekday_of_8_weeks():
    mondays = [TODAY - timedelta(weeks=k) for k in range(1, 9)]
    wellness = {d: {"rhr": 50.0 + i, "sleep_s": 25000.0} for i, d in enumerate(mondays)}
    wellness[TODAY - timedelta(weeks=9)] = {"rhr": 99.0}  # older than 8 weeks
    wellness[TODAY] = {"rhr": 99.0}  # today itself is not typical
    typical = fc.typical_wellness(wellness, TODAY + timedelta(days=7), TODAY)
    assert typical["rhr"] == pytest.approx(53.5) and typical["sleep_s"] == 25000.0
    assert typical["sleep_score"] is None and typical["body_battery_wake"] is None
    two = {d: {"rhr": 50.0} for d in mondays[:2]}
    assert fc.typical_wellness(two, TODAY + timedelta(days=7), TODAY)["rhr"] is None  # < 3 values
    loads = {mondays[0]: 80.0, mondays[1]: 60.0, mondays[2]: 40.0}  # 5 missing Mondays count as 0
    assert fc.typical_load(loads, TODAY + timedelta(days=7), TODAY) == 0.0
    assert fc.typical_load({d: 50.0 for d in mondays}, TODAY + timedelta(days=7), TODAY) == 50.0


def test_outlook_carries_ctl_atl_forward_and_scores_readiness():
    days = fc.outlook(
        today=TODAY,
        ctl_prev=50.0,
        atl_prev=60.0,
        load_today=0.0,
        wellness={},
        loads={},
        rhr_median28=50.0,
        sleep_s_median28=27000.0,
    )
    assert [d.day for d in days] == [TODAY + timedelta(days=i) for i in range(1, 8)]
    ctl, atl = 50.0 - 50.0 / 42, 60.0 - 60.0 / 7
    assert days[0].tsb == pytest.approx(ctl - atl)
    assert days[1].tsb == pytest.approx(ctl * (1 - 1 / 42) - atl * (1 - 1 / 7))
    assert days[0].readiness is None and days[0].band is None  # no typical wellness → no score


def test_outlook_readiness_matches_the_formula():
    tuesdays = [TODAY + timedelta(days=1) - timedelta(weeks=k) for k in range(1, 9)]
    wellness = {d: {"rhr": 52.0, "sleep_score": 80.0, "body_battery_wake": 70.0} for d in tuesdays}
    [first, *_] = fc.outlook(
        today=TODAY,
        ctl_prev=40.0,
        atl_prev=40.0,
        load_today=70.0,
        wellness=wellness,
        loads={},
        rhr_median28=50.0,
        sleep_s_median28=None,
    )
    tsb = (40 + 30 / 42) - (40 + 30 / 7)
    expected = readiness(
        rhr=52.0,
        rhr_median28=50.0,
        sleep_score=80.0,
        sleep_s=None,
        sleep_s_median28=None,
        body_battery_wake=70.0,
        tsb=tsb,
    )
    assert first.readiness == pytest.approx(expected.score) and first.band == expected.band


def day(offset, value):
    return fc.OutlookDay(TODAY + timedelta(days=offset), value, None, 0.0, 0.0, {})


def test_best_days():
    days = [day(1, 72.0), day(2, 80.0), day(3, 80.0), day(4, 69.9), day(5, None), day(6, 90.0)]
    available = [TODAY + timedelta(days=i) for i in (1, 2, 3, 4, 5)]  # Sunday (6) is a rest day
    assert fc.best_days(days, available) == [TODAY + timedelta(days=2), TODAY + timedelta(days=3)]
    assert fc.best_days([day(1, 69.0)], available) == []
