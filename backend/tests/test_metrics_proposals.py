"""Threshold proposals – METRICS §6.3.

# METRICS §6.3
- `threshold_speed_est` = max over trailing 90 days of best 1800 s gap_speed (fallback: 0.95 · best 1200 s).
  Propose when it differs from current by `> 2 %`.
- `lthr_est` (per sport) = max over trailing 90 days of the 1800 s HR best effort from activities with
  `if_pace ≥ 0.95` (run) or with the top-decile hrTSS/h (bike). Propose when `|Δ| > 3 bpm`.
Clarified 2026-09-29 (phase 4, proposed): "current" = the threshold valid today. For bikes, the activities
whose `hrtss / (moving_s / 3600)` is in the top 10 % (≥ the 90th percentile, at least one activity) among
the sport's activities of the window. No qualifying data → no proposal. Without a current threshold the
estimate is always proposed. Proposals round: speed to 0.01 m/s, LTHR to whole bpm.
"""

import math
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from training.metrics.efforts import (
    ThresholdProposal,
    lthr_missing_reason,
    propose_lthr,
    propose_threshold_speed,
    speed_missing_reason,
)

TODAY = date(2026, 9, 29)


def days_ago(n: int) -> date:
    return TODAY - timedelta(days=n)


def gap_efforts(rows: list[tuple[int, int, float]]) -> pd.DataFrame:
    """rows: (days ago, window_s, value)."""
    return pd.DataFrame(
        {
            "local_date": [days_ago(d) for d, _, _ in rows],
            "kind": ["gap_speed"] * len(rows),
            "window_s": [w for _, w, _ in rows],
            "value": [v for _, _, v in rows],
        },
        columns=["local_date", "kind", "window_s", "value"],
    )


# ---------------------------------------------------------------- threshold_speed


def test_speed_exactly_2_percent_not_proposed():
    p = propose_threshold_speed(gap_efforts([(5, 1800, 4.08)]), current=4.00, today=TODAY)
    assert isinstance(p, ThresholdProposal)
    assert p.sport == "run"
    assert p.field == "threshold_speed"
    assert p.estimate == pytest.approx(4.08)
    assert p.current == 4.00
    assert p.change == pytest.approx(0.02)
    assert p.propose is False


def test_speed_above_2_percent_proposed():
    p = propose_threshold_speed(gap_efforts([(5, 1800, 4.09)]), current=4.00, today=TODAY)
    assert p is not None
    assert p.change == pytest.approx(0.0225)
    assert p.propose is True


def test_speed_lower_exactly_2_percent_and_beyond():
    p = propose_threshold_speed(gap_efforts([(5, 1800, 3.92)]), current=4.00, today=TODAY)
    assert p is not None and p.propose is False and p.change == pytest.approx(-0.02)
    p = propose_threshold_speed(gap_efforts([(5, 1800, 3.91)]), current=4.00, today=TODAY)
    assert p is not None and p.propose is True


def test_speed_max_of_1800_in_window_and_basis():
    df = gap_efforts([(5, 1800, 4.10), (12, 1800, 4.20), (90, 1800, 4.60), (3, 1200, 4.80)])
    p = propose_threshold_speed(df, current=None, today=TODAY)
    assert p is not None
    assert p.estimate == pytest.approx(4.20)
    assert "1800" in p.basis
    assert days_ago(12).isoformat() in p.basis


def test_speed_edge_89_days_in():
    df = gap_efforts([(89, 1800, 4.50), (1, 1800, 4.00)])
    p = propose_threshold_speed(df, current=None, today=TODAY)
    assert p is not None and p.estimate == pytest.approx(4.50)


def test_speed_fallback_095_best_1200():
    df = gap_efforts([(5, 1200, 4.20), (6, 1200, 4.00), (7, 600, 5.00)])
    p = propose_threshold_speed(df, current=4.00, today=TODAY)
    assert p is not None
    assert p.estimate == pytest.approx(3.99)  # 0.95 · 4.20
    assert "1200" in p.basis
    assert "0.95" in p.basis
    assert p.propose is False  # −0.25 %


def test_speed_fallback_when_1800_only_outside_window():
    df = gap_efforts([(90, 1800, 4.50), (10, 1200, 4.00)])
    p = propose_threshold_speed(df, current=None, today=TODAY)
    assert p is not None and p.estimate == pytest.approx(3.80)


def test_speed_rounded_to_hundredths():
    p = propose_threshold_speed(gap_efforts([(1, 1800, 4.1234)]), current=None, today=TODAY)
    assert p is not None and p.estimate == 4.12
    p = propose_threshold_speed(gap_efforts([(1, 1800, 4.125)]), current=None, today=TODAY)
    assert p is not None and p.estimate == 4.13  # half up


def test_speed_no_current_always_proposed():
    p = propose_threshold_speed(gap_efforts([(1, 1800, 4.0)]), current=None, today=TODAY)
    assert p is not None
    assert p.current is None
    assert math.isnan(p.change)
    assert p.propose is True


def test_speed_no_data_none():
    assert propose_threshold_speed(gap_efforts([]), current=4.0, today=TODAY) is None
    assert propose_threshold_speed(gap_efforts([(100, 1800, 4.0)]), current=4.0, today=TODAY) is None
    assert propose_threshold_speed(gap_efforts([(1, 600, 4.0)]), current=4.0, today=TODAY) is None


def test_speed_ignores_other_kinds_and_nan():
    df = gap_efforts([(1, 1800, 4.0), (2, 1800, np.nan)])
    extra = pd.DataFrame({"local_date": [days_ago(1)], "kind": ["hr"], "window_s": [1800], "value": [180.0]})
    p = propose_threshold_speed(pd.concat([df, extra], ignore_index=True), current=None, today=TODAY)
    assert p is not None and p.estimate == pytest.approx(4.0)


# ---------------------------------------------------------------- lthr (run)


def hr_efforts(rows: list[tuple[int, int, float]]) -> pd.DataFrame:
    """rows: (activity_id, days ago, 1800 s HR value)."""
    return pd.DataFrame(
        {
            "activity_id": [a for a, _, _ in rows],
            "local_date": [days_ago(d) for _, d, _ in rows],
            "kind": ["hr"] * len(rows),
            "window_s": [1800] * len(rows),
            "value": [v for _, _, v in rows],
        },
        columns=["activity_id", "local_date", "kind", "window_s", "value"],
    )


def activities(rows: list[tuple]) -> pd.DataFrame:
    """rows: (activity_id, days ago, if_pace, hrtss, moving_s)."""
    return pd.DataFrame(
        {
            "activity_id": [r[0] for r in rows],
            "local_date": [days_ago(r[1]) for r in rows],
            "if_pace": [r[2] for r in rows],
            "hrtss": [r[3] for r in rows],
            "moving_s": [r[4] for r in rows],
        },
        columns=["activity_id", "local_date", "if_pace", "hrtss", "moving_s"],
    )


RUN_ACTS = activities(
    [
        (1, 5, 0.96, 80.0, 3600),
        (2, 6, 0.94, 90.0, 3600),  # if_pace below 0.95 → excluded
        (3, 7, 0.95, 70.0, 3600),  # exactly 0.95 → included
        (4, 8, np.nan, 60.0, 3600),  # no if_pace → excluded
    ]
)
RUN_HR = hr_efforts([(1, 5, 172.4), (2, 6, 180.0), (3, 7, 171.0), (4, 8, 185.0)])


def test_lthr_run_if_pace_filter_and_rounding():
    p = propose_lthr("run", RUN_HR, RUN_ACTS, current=None, today=TODAY)
    assert isinstance(p, ThresholdProposal)
    assert p.sport == "run"
    assert p.field == "lthr"
    assert p.estimate == 172.0  # max(172.4, 171) rounded; 180 and 185 are excluded
    assert p.propose is True
    assert math.isnan(p.change)
    assert "1800" in p.basis


def test_lthr_run_if_pace_boundary_included():
    acts = activities([(3, 7, 0.95, 70.0, 3600)])
    p = propose_lthr("run", hr_efforts([(3, 7, 171.0)]), acts, current=None, today=TODAY)
    assert p is not None and p.estimate == 171.0


def test_lthr_delta_3_vs_4_bpm():
    p = propose_lthr("run", RUN_HR, RUN_ACTS, current=169.0, today=TODAY)
    assert p is not None and p.change == 3.0 and p.propose is False
    p = propose_lthr("run", RUN_HR, RUN_ACTS, current=168.0, today=TODAY)
    assert p is not None and p.change == 4.0 and p.propose is True
    p = propose_lthr("run", RUN_HR, RUN_ACTS, current=175.0, today=TODAY)
    assert p is not None and p.change == -3.0 and p.propose is False
    p = propose_lthr("run", RUN_HR, RUN_ACTS, current=176.0, today=TODAY)
    assert p is not None and p.change == -4.0 and p.propose is True


def test_lthr_rounds_half_up():
    acts = activities([(1, 1, 1.0, 80.0, 3600)])
    p = propose_lthr("run", hr_efforts([(1, 1, 172.5)]), acts, current=None, today=TODAY)
    assert p is not None and p.estimate == 173.0


def test_lthr_run_90_day_window():
    acts = activities([(1, 89, 1.0, 80.0, 3600), (2, 90, 1.0, 80.0, 3600)])
    efforts = hr_efforts([(1, 89, 170.0), (2, 90, 190.0)])
    p = propose_lthr("run", efforts, acts, current=None, today=TODAY)
    assert p is not None and p.estimate == 170.0


def test_lthr_ignores_other_windows():
    efforts = hr_efforts([(1, 5, 172.0)])
    extra = efforts.assign(window_s=1200, value=190.0)
    both = pd.concat([efforts, extra], ignore_index=True)
    p = propose_lthr("run", both, RUN_ACTS, current=None, today=TODAY)
    assert p is not None and p.estimate == 172.0


def test_lthr_no_qualifying_data_none():
    acts = activities([(2, 6, 0.94, 90.0, 3600)])
    assert propose_lthr("run", hr_efforts([(2, 6, 180.0)]), acts, current=170.0, today=TODAY) is None
    assert propose_lthr("run", hr_efforts([]), RUN_ACTS, current=170.0, today=TODAY) is None
    assert propose_lthr("run", RUN_HR, activities([]), current=170.0, today=TODAY) is None


def test_lthr_unknown_sport_raises():
    with pytest.raises(ValueError):
        propose_lthr("other", RUN_HR, RUN_ACTS, current=None, today=TODAY)


# ---------------------------------------------------------------- lthr (bike, top decile of hrTSS/h)


def bike_acts(rates: list[float], *, start_id: int = 1, days: int = 5) -> pd.DataFrame:
    """One activity per hrTSS/h rate (1 h each, if_pace NaN)."""
    return activities([(start_id + i, days, np.nan, r, 3600) for i, r in enumerate(rates)])


def test_bike_top_decile_of_ten():
    # rates 10..100 → 90th percentile (linear) = 91 → only the 100/h ride qualifies.
    acts = bike_acts([10.0 * k for k in range(1, 11)])
    hr = [175.0] * 9 + [165.0]  # the top ride has the lowest HR – the others must not count
    efforts = hr_efforts([(i + 1, 5, v) for i, v in enumerate(hr)])
    p = propose_lthr("bike", efforts, acts, current=None, today=TODAY)
    assert p is not None
    assert p.sport == "bike"
    assert p.estimate == 165.0


def test_bike_top_decile_of_eleven_takes_two():
    # rates 0..100 step 10 → 90th percentile = 90 → rides at 90 and 100 qualify.
    acts = bike_acts([10.0 * k for k in range(11)])
    hr = [180.0] * 9 + [168.0, 166.0]
    efforts = hr_efforts([(i + 1, 5, v) for i, v in enumerate(hr)])
    p = propose_lthr("bike", efforts, acts, current=None, today=TODAY)
    assert p is not None and p.estimate == 168.0


def fill(
    acts: pd.DataFrame, efforts: pd.DataFrame, *, hrtss: float = 1.0
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Add 2 easy rides (hrTSS/h 1, avg HR 100, 30-min HR 100) so a test meets the 3-ride minimum without
    changing which ride is on top."""
    easy = activities([(101, 5, np.nan, hrtss, 3600), (102, 5, np.nan, hrtss, 3600)]).assign(avg_hr=100.0)
    return (
        pd.concat([acts, easy], ignore_index=True),
        pd.concat([efforts, hr_efforts([(101, 5, 100.0), (102, 5, 100.0)])], ignore_index=True),
    )


def test_bike_needs_at_least_3_rides():
    # changed 2026-10-25: one or two rides with a 30-min HR effort give no proposal, three do
    one = (hr_efforts([(1, 5, 160.0)]), bike_acts([40.0]))
    two = (hr_efforts([(1, 5, 160.0), (2, 5, 150.0)]), bike_acts([40.0, 50.0]))
    assert propose_lthr("bike", *one, current=None, today=TODAY) is None
    assert propose_lthr("bike", *two, current=None, today=TODAY) is None
    assert lthr_missing_reason("bike", *two, today=TODAY) == (
        "only 2 ride(s) with 30 min of HR without a pause and hrTSS (at least 3 needed)"
    )
    three = (hr_efforts([(1, 5, 160.0), (2, 5, 150.0), (3, 5, 158.0)]), bike_acts([40.0, 50.0, 60.0]))
    p = propose_lthr("bike", *three, current=None, today=TODAY)
    assert p is not None and p.estimate == 158.0


def test_bike_two_activities_only_the_higher():
    acts, efforts = fill(bike_acts([50.0, 80.0]), hr_efforts([(1, 5, 170.0), (2, 5, 160.0)]))
    p = propose_lthr("bike", efforts, acts, current=None, today=TODAY)
    assert p is not None and p.estimate == 160.0


def test_bike_equal_rates_all_qualify():
    acts = bike_acts([60.0, 60.0, 60.0])
    efforts = hr_efforts([(1, 5, 150.0), (2, 5, 162.0), (3, 5, 155.0)])
    p = propose_lthr("bike", efforts, acts, current=None, today=TODAY)
    assert p is not None and p.estimate == 162.0


def test_bike_rate_is_per_hour():
    # ride 1: 50 hrTSS in 30 min = 100/h; ride 2: 90 hrTSS in 2 h = 45/h → ride 1 is the top one.
    acts, efforts = fill(
        activities([(1, 5, np.nan, 50.0, 1800), (2, 5, np.nan, 90.0, 7200)]),
        hr_efforts([(1, 5, 158.0), (2, 5, 170.0)]),
    )
    p = propose_lthr("bike", efforts, acts, current=None, today=TODAY)
    assert p is not None and p.estimate == 158.0


def test_bike_population_only_window_and_valid_rate():
    # an old ride with a huge rate and a ride without hrTSS do not enter the percentile
    acts = pd.concat(
        [
            bike_acts([50.0, 80.0]),
            activities([(3, 90, np.nan, 500.0, 3600), (4, 5, np.nan, np.nan, 3600), (5, 5, np.nan, 10.0, 0)]),
        ],
        ignore_index=True,
    )
    efforts = hr_efforts([(1, 5, 170.0), (2, 5, 160.0), (3, 90, 190.0), (4, 5, 185.0), (5, 5, 186.0)])
    acts, efforts = fill(acts, efforts)
    p = propose_lthr("bike", efforts, acts, current=None, today=TODAY)
    assert p is not None and p.estimate == 160.0


def test_bike_only_rides_with_1800_effort_enter_the_percentile():
    # changed 2026-10-25: the 80/h ride has no 30-min HR effort, so it cannot block the 50/h ride
    acts, efforts = fill(bike_acts([50.0, 80.0]), hr_efforts([(1, 5, 170.0)]))
    p = propose_lthr("bike", efforts, acts, current=None, today=TODAY)
    assert p is not None and p.estimate == 170.0
    assert p.basis.endswith("1 top-decile hrTSS/h ride(s) of 3 with 30 min of HR")


def test_bike_without_any_1800_effort_none():
    acts = bike_acts([50.0, 80.0])
    assert (
        propose_lthr("bike", hr_efforts([(1, 5, 170.0)]).iloc[0:0], acts, current=None, today=TODAY) is None
    )


def test_bike_delta_rule():
    acts, efforts = fill(bike_acts([40.0]), hr_efforts([(1, 5, 160.0)]))
    p = propose_lthr("bike", efforts, acts, current=156.0, today=TODAY)
    assert p is not None and p.propose is True and p.change == 4.0


# ------------------------------------------------ lthr (bike bootstrap, METRICS §6.3 changed 2026-10-25)


def rides_without_hrtss(avg_hrs: list[float], *, days: int = 5) -> pd.DataFrame:
    """Rides without a bike threshold: hrTSS NaN, ranked by avg_hr."""
    acts = activities([(i + 1, days, np.nan, np.nan, 3600) for i in range(len(avg_hrs))])
    return acts.assign(avg_hr=avg_hrs)


def test_bike_bootstrap_ranks_by_avg_hr_without_any_hrtss():
    # avg HR 120..165 step 5 (10 rides) → 90th percentile = 160.5 → only the 165 ride qualifies.
    acts = rides_without_hrtss([120.0 + 5 * k for k in range(10)])
    efforts = hr_efforts([(i + 1, 5, 175.0 if i < 9 else 168.0) for i in range(10)])
    p = propose_lthr("bike", efforts, acts, current=None, today=TODAY)
    assert p is not None and p.estimate == 168.0 and p.propose is True
    assert "average HR" in p.basis


def test_bike_bootstrap_ignores_rides_outside_window_and_without_avg_hr():
    acts = pd.concat(
        [rides_without_hrtss([140.0, 150.0]), rides_without_hrtss([190.0], days=90).assign(activity_id=3)],
        ignore_index=True,
    )
    acts.loc[len(acts)] = {**acts.iloc[0].to_dict(), "activity_id": 4, "avg_hr": np.nan}
    efforts = hr_efforts([(1, 5, 171.0), (2, 5, 163.0), (3, 90, 185.0), (4, 5, 189.0)])
    acts, efforts = fill(acts, efforts, hrtss=np.nan)
    p = propose_lthr("bike", efforts, acts, current=None, today=TODAY)
    assert p is not None and p.estimate == 163.0


def test_bike_hrtss_rule_wins_when_any_ride_has_hrtss():
    # one ride has hrTSS → the hrTSS/h rule applies, even if another ride has a higher avg_hr
    acts = activities([(1, 5, np.nan, 60.0, 3600), (2, 5, np.nan, np.nan, 3600)]).assign(
        avg_hr=[140.0, 170.0]
    )
    acts, efforts = fill(acts, hr_efforts([(1, 5, 158.0), (2, 5, 180.0)]))
    p = propose_lthr("bike", efforts, acts, current=None, today=TODAY)
    assert p is not None and p.estimate == 158.0 and "hrTSS/h" in p.basis


def test_bike_no_hrtss_and_no_avg_hr_column_none():
    acts = activities([(1, 5, np.nan, np.nan, 3600)])
    assert propose_lthr("bike", hr_efforts([(1, 5, 160.0)]), acts, current=None, today=TODAY) is None


# ------------------------------------------------------------ why a proposal is missing (not part of §6.3)


def test_missing_reason_is_none_when_there_is_a_proposal():
    acts, efforts = fill(bike_acts([40.0]), hr_efforts([(1, 5, 160.0)]))
    assert lthr_missing_reason("bike", efforts, acts, today=TODAY) is None
    assert speed_missing_reason(gap_efforts([(5, 1800, 3.0)]), today=TODAY) is None


def test_missing_reasons_for_rides():
    assert lthr_missing_reason("bike", hr_efforts([]), activities([]), today=TODAY) == (
        "no rides in the last 90 days"
    )
    reason = lthr_missing_reason("bike", hr_efforts([(9, 5, 160.0)]), bike_acts([40.0, 60.0]), today=TODAY)
    assert reason == "none of 2 rides has 30 min of HR without a pause"


def test_missing_reasons_for_runs():
    slow = activities([(1, 5, 0.80, 50.0, 3600), (2, 5, 0.87, 50.0, 3600)])
    assert lthr_missing_reason("run", hr_efforts([(1, 5, 150.0)]), slow, today=TODAY) == (
        "none of 2 runs reached if_pace ≥ 0.95 (highest 0.870)"
    )
    no_threshold = activities([(1, 5, np.nan, 50.0, 3600)])
    assert "no if_pace (no threshold pace)" in lthr_missing_reason(
        "run", hr_efforts([]), no_threshold, today=TODAY
    )
    fast = activities([(1, 5, 0.97, 80.0, 1500)])
    assert lthr_missing_reason("run", hr_efforts([]), fast, today=TODAY) == (
        "1 run(s) with if_pace ≥ 0.95, none with 30 min of HR without a pause"
    )


def test_speed_missing_reason():
    assert speed_missing_reason(gap_efforts([(5, 600, 3.0)]), today=TODAY) == (
        "no run of the last 90 days has 20 min of GAP without a pause"
    )


def test_highest_if_pace_is_not_rounded_up_to_the_limit():
    almost = activities([(1, 5, 0.9499, 50.0, 3600)])
    assert lthr_missing_reason("run", hr_efforts([]), almost, today=TODAY).endswith("(highest 0.949)")


def test_no_runs_at_all_for_the_speed_estimate():
    assert (
        speed_missing_reason(gap_efforts([]), today=TODAY) == "no runs with GAP efforts in the last 90 days"
    )


def test_bike_bootstrap_is_decided_on_every_ride_of_the_window():
    # ride 1 has hrTSS (a threshold exists) but no 30-min effort; rides 2–3 have the effort but no hrTSS
    # (threshold valid from mid-window) → no bootstrap, and the population has no hrTSS/h → no proposal
    acts = activities(
        [(1, 5, np.nan, 60.0, 3600), (2, 5, np.nan, np.nan, 3600), (3, 5, np.nan, np.nan, 3600)]
    )
    acts = acts.assign(avg_hr=[150.0, 160.0, 170.0])
    efforts = hr_efforts([(2, 5, 165.0), (3, 5, 172.0)])
    assert propose_lthr("bike", efforts, acts, current=165.0, today=TODAY) is None
    assert (
        lthr_missing_reason("bike", efforts, acts, today=TODAY)
        == "2 ride(s) with 30 min of HR, none with hrTSS"
    )


def test_bike_bootstrap_reason_without_avg_hr():
    acts = rides_without_hrtss([np.nan, np.nan])
    reason = lthr_missing_reason("bike", hr_efforts([(1, 5, 160.0)]), acts, today=TODAY)
    assert reason == "1 ride(s) with 30 min of HR, none with an average HR"
