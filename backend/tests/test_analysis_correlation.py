"""METRICS §9: constants, rpe_expected and the day-level dataset builder."""

import numpy as np
import pandas as pd
import pytest

from training.analysis.correlation import (
    CONTROLS,
    EXTRA_PREDICTORS,
    MIN_N,
    N_BOOT,
    OUTCOMES,
    SPORTS,
    VARIANTS,
    build_dataset,
    predictor_columns,
    rpe_expected,
)

from .correlation_seeding import (
    TOL,
    activities_frame,
    activity,
    daily_frame,
    ts,
    wellness_frame,
)

# --------------------------------------------------------------------------------------------------
# constants and rpe_expected


def test_constants() -> None:
    assert (MIN_N, N_BOOT) == (30, 1000)
    assert SPORTS == ("run", "bike")
    assert VARIANTS == ("lag0", "lag1", "mean3")
    assert EXTRA_PREDICTORS == ("sleep_debt_7",)
    assert CONTROLS == ("tsb", "atl_prev", "load_prev")
    assert OUTCOMES == ("ef", "decoupling_pct", "pace_at_ref_hr_day", "rpe_residual")


def test_predictor_columns() -> None:
    columns = predictor_columns()
    assert len(columns) == 19
    assert columns[:3] == ["sleep_s_lag0", "sleep_s_lag1", "sleep_s_mean3"]
    assert columns[-1] == "sleep_debt_7"
    assert "body_battery_wake_mean3" in columns


@pytest.mark.parametrize(
    ("if_primary", "expected"),
    [
        (0.5, 1.0),  # lower clamp edge
        (0.3, 1.0),  # clamped at 0
        (0.85, 5.5),  # (0.85 − 0.5) / 0.7 = 0.5 → 1 + 4.5
        (1.2, 10.0),  # upper clamp edge
        (1.5, 10.0),  # clamped at 1
        (0.64, 1.0 + 9.0 * 0.2),  # (0.64 − 0.5) / 0.7 = 0.2
    ],
)
def test_rpe_expected(if_primary: float, expected: float) -> None:
    assert rpe_expected(if_primary) == pytest.approx(expected, abs=TOL)


def test_rpe_expected_nan() -> None:
    assert np.isnan(rpe_expected(float("nan")))


# --------------------------------------------------------------------------------------------------
# build_dataset


def test_build_dataset_columns_index_and_sorting() -> None:
    acts = activities_frame([activity(2, 7), activity(1, 3)])
    ds = build_dataset(acts, wellness_frame({3: {"sleep_s": 1.0}}), daily_frame(), "run")
    assert list(ds.columns) == ["activity_id", *OUTCOMES, *predictor_columns(), *CONTROLS]
    assert list(ds.index) == [ts(3), ts(7)]
    assert ds.index.name == "date"
    assert list(ds["activity_id"]) == [1, 2]


def test_build_dataset_empty() -> None:
    ds = build_dataset(activities_frame([]), wellness_frame({}), daily_frame(), "run")
    assert ds.empty
    assert list(ds.columns) == ["activity_id", *OUTCOMES, *predictor_columns(), *CONTROLS]


def test_build_dataset_rejects_other_sport() -> None:
    with pytest.raises(ValueError):
        build_dataset(activities_frame([]), wellness_frame({}), daily_frame(), "other")


def test_longest_qualifying_activity_is_picked() -> None:
    acts = activities_frame(
        [
            activity(10, 2, moving_s=1800, ef=1.0),
            activity(11, 2, moving_s=3600, ef=2.0),
            # longest run, but no outcome at all (not steady, no rpe) → not qualifying
            activity(12, 2, moving_s=5400, ef=None, decoupling_pct=None, pace_at_ref_hr_day=None),
            # longest activity of the day, but another sport
            activity(13, 2, sport="bike", moving_s=7200, ef=9.0),
            activity(14, 2, sport="other", moving_s=9000, ef=9.0),
        ]
    )
    ds = build_dataset(acts, wellness_frame({}), daily_frame(), "run")
    assert len(ds) == 1
    assert ds.loc[ts(2), "activity_id"] == 11
    assert ds.loc[ts(2), "ef"] == 2.0


def test_day_without_any_outcome_is_not_qualifying() -> None:
    acts = activities_frame(
        [activity(1, 2, ef=None, decoupling_pct=None, pace_at_ref_hr_day=None), activity(2, 4)]
    )
    ds = build_dataset(acts, wellness_frame({}), daily_frame(), "run")
    assert list(ds.index) == [ts(4)]


def test_rpe_only_activity_qualifies() -> None:
    acts = activities_frame([activity(1, 2, ef=None, decoupling_pct=None, pace_at_ref_hr_day=None, rpe=6)])
    ds = build_dataset(acts, wellness_frame({}), daily_frame(), "run")
    assert list(ds.index) == [ts(2)]
    assert ds.loc[ts(2), "rpe_residual"] == pytest.approx(0.5, abs=TOL)  # 6 − 5.5 (if_pace 0.85)


def test_rpe_residual_uses_primary_if() -> None:
    acts = activities_frame(
        [
            # rTSS → if_pace 0.85 → expected 5.5 → 6 − 5.5
            activity(1, 1, load_method="rtss", if_pace=0.85, if_hr=1.2, rpe=6),
            # hrTSS → if_hr 0.5 → expected 1 → 3 − 1
            activity(2, 2, load_method="hrtss", if_hr=0.5, if_pace=1.2, rpe=3),
            # no load method → if_hr 1.2 → expected 10
            activity(3, 3, load_method=None, if_hr=1.2, if_pace=0.5, rpe=10),
            # METRICS spelling "rTSS" is accepted as well → if_pace 1.2 → expected 10
            activity(4, 4, load_method="rTSS", if_hr=0.5, if_pace=1.2, rpe=7),
            # no rpe → null
            activity(5, 5, rpe=None),
            # rpe but no IF_primary → null
            activity(6, 6, load_method="rtss", if_pace=np.nan, if_hr=0.9, rpe=5),
        ]
    )
    ds = build_dataset(acts, wellness_frame({}), daily_frame(), "run")
    residual = ds["rpe_residual"]
    assert residual[ts(1)] == pytest.approx(0.5, abs=TOL)
    assert residual[ts(2)] == pytest.approx(2.0, abs=TOL)
    assert residual[ts(3)] == pytest.approx(0.0, abs=TOL)
    assert residual[ts(4)] == pytest.approx(-3.0, abs=TOL)
    assert np.isnan(residual[ts(5)])
    assert np.isnan(residual[ts(6)])


def test_lag_alignment_on_sparse_wellness() -> None:
    # wellness exists only on days 3, 4, 8, 10, 15
    wellness = wellness_frame(
        {
            3: {"sleep_s": 100.0},
            4: {"sleep_s": 200.0, "rhr": 50.0},
            8: {"sleep_s": 800.0},
            10: {"sleep_s": 1000.0, "sleep_debt_7": 3600.0},
            15: {"sleep_s": 1500.0},
        }
    )
    acts = activities_frame([activity(1, 5), activity(2, 10), activity(3, 15)])
    ds = build_dataset(acts, wellness, daily_frame(), "run")

    # day 5: no row for 5 → lag0 NaN; lag1 = day 4; mean3 = days 3–5 → (100 + 200) / 2
    assert np.isnan(ds.loc[ts(5), "sleep_s_lag0"])
    assert ds.loc[ts(5), "sleep_s_lag1"] == 200.0
    assert ds.loc[ts(5), "sleep_s_mean3"] == 150.0
    assert ds.loc[ts(5), "rhr_lag1"] == 50.0
    assert np.isnan(ds.loc[ts(5), "rhr_mean3"])  # only one valid value (day 4)
    # day 10: lag1 is calendar day 9 (missing), NOT the previous row (day 8)
    assert ds.loc[ts(10), "sleep_s_lag0"] == 1000.0
    assert np.isnan(ds.loc[ts(10), "sleep_s_lag1"])
    assert ds.loc[ts(10), "sleep_s_mean3"] == 900.0  # days 8–10 → (800 + 1000) / 2
    # day 15: days 13, 14 missing → mean3 has one valid value → NaN
    assert ds.loc[ts(15), "sleep_s_lag0"] == 1500.0
    assert np.isnan(ds.loc[ts(15), "sleep_s_lag1"])
    assert np.isnan(ds.loc[ts(15), "sleep_s_mean3"])
    # sleep_debt_7 is lag0 only
    assert ds.loc[ts(10), "sleep_debt_7"] == 3600.0
    assert np.isnan(ds.loc[ts(5), "sleep_debt_7"])
    assert np.isnan(ds.loc[ts(15), "sleep_debt_7"])


def test_wellness_with_datetime_index() -> None:
    wellness = wellness_frame({4: {"sleep_s": 200.0}, 5: {"sleep_s": 300.0}})
    wellness.index = pd.DatetimeIndex([ts(4), ts(5)], name="date")
    ds = build_dataset(activities_frame([activity(1, 5)]), wellness, daily_frame(), "run")
    assert ds.loc[ts(5), "sleep_s_lag0"] == 300.0
    assert ds.loc[ts(5), "sleep_s_lag1"] == 200.0
    assert ds.loc[ts(5), "sleep_s_mean3"] == 250.0


def test_controls_use_day_and_previous_day() -> None:
    acts = activities_frame([activity(1, 0), activity(2, 5)])
    ds = build_dataset(acts, wellness_frame({}), daily_frame(first=0, last=20), "run")
    # tsb[D] = 100 + D, atl[D−1] = 200 + D − 1, load_total[D−1] = 300 + D − 1
    assert ds.loc[ts(5), "tsb"] == 105.0
    assert ds.loc[ts(5), "atl_prev"] == 204.0
    assert ds.loc[ts(5), "load_prev"] == 304.0
    # day 0 is the first daily row → D−1 does not exist
    assert ds.loc[ts(0), "tsb"] == 100.0
    assert np.isnan(ds.loc[ts(0), "atl_prev"])
    assert np.isnan(ds.loc[ts(0), "load_prev"])


def test_bike_dataset_has_no_pace_outcome() -> None:
    acts = activities_frame(
        [
            activity(1, 1, sport="bike", ef=1.1, pace_at_ref_hr_day=3.0),
            # only a pace value → not an outcome for bike → not qualifying
            activity(2, 2, sport="bike", ef=None, decoupling_pct=None, pace_at_ref_hr_day=3.0),
            activity(3, 3, sport="run"),
        ]
    )
    ds = build_dataset(acts, wellness_frame({}), daily_frame(), "bike")
    assert list(ds.index) == [ts(1)]
    assert ds["pace_at_ref_hr_day"].isna().all()
    assert ds.loc[ts(1), "ef"] == 1.1
