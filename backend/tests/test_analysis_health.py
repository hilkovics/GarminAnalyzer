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


# --- boundaries, gates and branches (spec review B1) --------------------------------------------------------


def test_minimum_counts_at_the_boundary():
    t = h.trends(series([1.0] * 14))
    assert np.isnan(t["mean28"].iloc[12]) and t["mean28"].iloc[13] == 1.0  # 13 vs 14 values
    assert h.monthly(series([5.0] * 10)).to_dict() == {"2026-01": 5.0}  # exactly 10 values
    today = START + timedelta(days=55)
    gaps = [np.nan] * 56
    for i in list(range(14)) + list(range(28, 42)):  # exactly 14 values in each window
        gaps[i] = float(i)
    assert h.recent_change(series(gaps), today, None).recent is not None
    gaps[41] = np.nan  # 13 in the recent window
    assert h.recent_change(series(gaps), today, None).recent is None


def test_change_windows_are_exactly_the_two_28_day_blocks():
    today = START + timedelta(days=56)  # 57 values: day 0 is outside both windows
    values = [1000.0] + [float(i) for i in range(1, 57)]
    c = h.recent_change(series(values), today, None)
    assert c.previous == pytest.approx(np.mean(range(1, 29))) and c.recent == pytest.approx(
        np.mean(range(29, 57))
    )


def test_notable_is_p_below_005_and_better_direction(monkeypatch):
    today = START + timedelta(days=55)
    values = [60.0] * 28 + [50.0] * 28  # resting HR down = better
    monkeypatch.setattr(h.stats, "mannwhitneyu", lambda a, b, alternative: type("R", (), {"pvalue": 0.05})())
    assert not h.recent_change(series(values), today, "down").notable
    monkeypatch.setattr(h.stats, "mannwhitneyu", lambda a, b, alternative: type("R", (), {"pvalue": 0.049})())
    change = h.recent_change(series(values), today, "down")
    assert change.notable and change.direction == "better"
    assert h.recent_change(series(values), today, "up").direction == "worse"


def test_relative_to_a_negative_normal_uses_its_size():
    t = h.trends(series([-10.0] * 10 + [-5.0] * 4))
    # mean7 = (3 · −10 + 4 · −5) / 7, normal −10 → above the normal = positive %
    assert t["pct"].iloc[13] == pytest.approx(((-50 / 7) + 10) / 10 * 100) and t["pct"].iloc[13] > 0


def test_same_day_pairs_skip_every_family():
    keys = ["body_battery_wake", "bb_charge", "stress_avg", "stress_high_s", "steps", "load", "rhr"]
    same_day = {frozenset((x, y)) for x, y, lag in h._pairs(keys) if lag == 0}
    for a, b in [("body_battery_wake", "bb_charge"), ("stress_avg", "stress_high_s"), ("steps", "load")]:
        assert frozenset((a, b)) not in same_day
    assert (
        frozenset(("body_battery_wake", "stress_avg")) in same_day and frozenset(("steps", "rhr")) in same_day
    )
    assert ("bb_charge", "body_battery_wake", 1) in h._pairs(keys)  # next-day pairs are all kept


def test_fisher_ci_uses_the_spearman_standard_error():
    low, high = h._fisher_ci(0.5, 103)
    z, se = np.arctanh(0.5), 1.03 / 10
    assert (low, high) == pytest.approx((np.tanh(z - 1.96 * se), np.tanh(z + 1.96 * se)))


def test_contrast_takes_exact_quarters_by_rank():
    assert h._contrast(np.arange(19.0), np.arange(19.0)) is None  # ⌊19 / 4⌋ = 4 < 5
    assert h._contrast(np.arange(20.0), np.arange(20.0) * 10) == pytest.approx(170 - 20)
    zeros = np.array([0.0] * 12 + [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0])  # 60 % ties at the bottom
    y = np.arange(20.0)
    assert h._contrast(zeros, y) == pytest.approx(np.mean(y[15:]) - np.mean(y[:5]))


def test_findings_need_rho_02_and_the_bh_gate(monkeypatch):
    rng = np.random.default_rng(11)
    n = 1000
    x = rng.normal(0, 1, n)
    y = 0.15 * x + rng.normal(0, 1, n)  # weak but very significant
    index = [START + timedelta(days=i) for i in range(n)]
    frame = pd.DataFrame({"rhr": x, "sleep_score": y}, index=index)
    same_day = next(r for r in h.relationships(frame) if r.lag == 0)
    assert same_day.p < 1e-3 and 0 < abs(same_day.rho) < h.RHO_FINDING and not same_day.finding
    strong = frame.assign(sleep_score=x + rng.normal(0, 0.3, n))
    assert any(r.finding for r in h.relationships(strong))
    monkeypatch.setattr(h, "benjamini_hochberg", lambda p, q=0.05: [False] * len(p))
    assert not any(r.finding for r in h.relationships(strong))


def test_contrast_is_in_raw_units_and_constant_columns_are_skipped(monkeypatch):
    seen = {}
    real = h._contrast
    monkeypatch.setattr(
        h, "_contrast", lambda xd, y: seen.setdefault("y", y.copy()) is not None and real(xd, y)
    )
    f = frame()
    f["flat"] = 5.0
    results = h.relationships(f[["stress_avg", "sleep_s", "flat"]].rename(columns={"flat": "rhr"}))
    assert all("rhr" not in (r.x, r.y) for r in results)  # a constant metric has no deviations to rank
    assert seen["y"].min() > 1000  # raw sleep seconds, not deviations around 0
