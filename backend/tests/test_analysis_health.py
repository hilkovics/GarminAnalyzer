"""Health trends and relationships (METRICS §12) with known answers – pure, no DB."""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from training.analysis import health as h

START = date(2026, 1, 1)


def series(values, start=START) -> pd.Series:
    return pd.Series(values, index=[start + timedelta(days=i) for i in range(len(values))], dtype=float)


def test_calendar_fills_missing_days():
    frame = pd.DataFrame({"rhr": [50.0, 52.0]}, index=[START, START + timedelta(days=3)])
    full = h.calendar(frame, end=START + timedelta(days=4))
    assert list(full.index) == [START + timedelta(days=i) for i in range(5)]
    assert full["rhr"].isna().sum() == 3


def test_trends_rolling_means_and_normal_band():
    values = [50.0] * 10 + [60.0]
    t = h.trends(series(values))
    assert np.isnan(t["mean7"].iloc[2]) and t["mean7"].iloc[3] == 50.0  # ≥ 4 values
    assert t["mean7"].iloc[10] == pytest.approx((6 * 50 + 60) / 7)
    assert np.isnan(t["median28"].iloc[6]) and t["median28"].iloc[7] == 50.0  # 7 days before
    assert t["median28"].iloc[10] == 50.0 and t["mad28"].iloc[10] == 0.0  # the day itself is excluded
    assert np.isnan(t["mean28"].iloc[12 - 2])  # < 14 values
    assert t["pct"].iloc[10] == pytest.approx(((6 * 50 + 60) / 7 - 50) / 50 * 100)
    assert np.isnan(t["pct"].iloc[6])  # no normal yet
    zero = h.trends(series([0.0] * 10))
    assert zero["pct"].isna().all()  # a normal of 0 has no relative scale


def test_mad_of_the_28_days_before():
    values = [float(v) for v in range(1, 30)]  # day 28 sees 1 … 28
    t = h.trends(series(values))
    assert t["median28"].iloc[28] == 14.5 and t["mad28"].iloc[28] == 7.0


def test_monthly_means_need_10_values():
    jan = [10.0] * 31
    feb = [20.0] * 9 + [np.nan] * 19
    m = h.monthly(series(jan + feb))
    assert m.to_dict() == {"2026-01": 10.0}


def test_recent_change_direction_and_minimum():
    today = START + timedelta(days=55)
    rng = np.random.default_rng(3)
    values = list(50 + rng.normal(0, 1, 28)) + list(60 + rng.normal(0, 1, 28))
    change = h.recent_change(series(values), today, "down")  # resting HR up = worse
    assert change.notable and change.direction == "worse"
    assert change.diff == pytest.approx(change.recent - change.previous)
    assert change.pct == pytest.approx(change.diff / change.previous)
    assert h.recent_change(series(values), today, None).direction is None
    flat = h.recent_change(series([50.0] * 56), today, "down")
    assert flat.p == 1.0 and not flat.notable and flat.diff == 0.0
    short = h.recent_change(series([50.0] * 40), today, "up")  # previous window has < 14 values
    assert short.recent is None and not short.notable


def test_benjamini_hochberg():
    assert h.benjamini_hochberg([0.01, 0.04, 0.03, 0.2]) == [True, False, False, False]
    assert h.benjamini_hochberg([0.01, 0.02, 0.03]) == [True, True, True]
    assert h.benjamini_hochberg([]) == []


def frame(n=120, seed=0):
    rng = np.random.default_rng(seed)
    stress = 30 + rng.normal(0, 5, n)
    sleep = np.empty(n)
    sleep[0] = 7 * 3600
    sleep[1:] = 7 * 3600 - 300 * (stress[:-1] - 30)  # more stress on day D → less sleep the next night
    noise = rng.normal(0, 1, n)
    deep = sleep * 0.2  # same family as sleep_s
    index = [START + timedelta(days=i) for i in range(n)]
    return pd.DataFrame(
        {"stress_avg": stress, "sleep_s": sleep, "deep_s": deep, "rhr": 50 + noise}, index=index
    )


def test_relationships_find_a_next_day_effect_and_skip_trivial_pairs():
    results = h.relationships(frame())
    top = results[0]
    assert (top.x, top.y, top.lag, top.finding) == ("stress_avg", "sleep_s", 1, True)
    assert top.rho < -0.9 and top.ci_low < top.rho < top.ci_high and top.contrast < 0
    assert not any(r.lag == 0 and {r.x, r.y} == {"sleep_s", "deep_s"} for r in results)  # one family
    noise = [r for r in results if "rhr" in (r.x, r.y)]
    assert noise and not any(r.finding for r in noise)
    assert all(r.n >= h.MIN_N for r in results)


def test_relationships_need_30_days():
    assert h.relationships(frame(n=36)) == []  # 7 days of baseline warm-up leave < 30 pairs
