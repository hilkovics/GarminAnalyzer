"""Sleep ↔ performance correlation: dataset, Spearman / partial / bootstrap / quartile contrast (METRICS §9).

All inputs are synthetic with known answers. The expected values are derived in the comments; the
statistical ones (planted correlation / confounder) use a fixed rng seed, so they are deterministic.
"""

import time
import warnings
from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from training.analysis.correlation import (
    BASE_PREDICTORS,
    CONTROLS,
    EXTRA_PREDICTORS,
    MIN_N,
    N_BOOT,
    OUTCOMES,
    SPORTS,
    VARIANTS,
    CorrelationResult,
    build_dataset,
    correlate,
    correlations,
    predictor_columns,
    rpe_expected,
)
from training.analysis.stats import quartile_contrast_rows, residualize_rows, spearman_rows

TOL = 1e-9
D0 = date(2026, 3, 2)
H = 3600.0

ACTIVITY_COLUMNS = [
    "activity_id",
    "local_date",
    "sport",
    "moving_s",
    "load_method",
    "if_hr",
    "if_pace",
    "ef",
    "decoupling_pct",
    "pace_at_ref_hr_day",
    "rpe",
]


# --------------------------------------------------------------------------------------------------
# synthetic inputs


def day(i: int) -> date:
    return D0 + timedelta(days=i)


def ts(i: int) -> pd.Timestamp:
    return pd.Timestamp(day(i))


def activity(
    activity_id: int,
    i: int,
    *,
    sport: str = "run",
    moving_s: float = H,
    load_method: str | None = "rtss",
    if_hr: float = 0.8,
    if_pace: float = 0.85,
    ef: float | None = 1.5,
    decoupling_pct: float | None = 3.0,
    pace_at_ref_hr_day: float | None = 3.2,
    rpe: float | None = None,
) -> dict:
    return {
        "activity_id": activity_id,
        "local_date": day(i),
        "sport": sport,
        "moving_s": moving_s,
        "load_method": load_method,
        "if_hr": if_hr,
        "if_pace": if_pace,
        "ef": ef,
        "decoupling_pct": decoupling_pct,
        "pace_at_ref_hr_day": pace_at_ref_hr_day,
        "rpe": rpe,
    }


def activities_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=ACTIVITY_COLUMNS)


def wellness_frame(rows: dict[int, dict[str, float]]) -> pd.DataFrame:
    """Sparse wellness: only the given day offsets exist, indexed by `datetime.date`."""
    columns = [*BASE_PREDICTORS, "sleep_debt_7"]
    index = pd.Index([day(i) for i in sorted(rows)], name="date")
    data = [[rows[i].get(c, np.nan) for c in columns] for i in sorted(rows)]
    return pd.DataFrame(data, index=index, columns=columns, dtype=float)


def daily_frame(first: int = 0, last: int = 20) -> pd.DataFrame:
    """Full daily series; tsb = 100 + i, atl = 200 + i, load_total = 300 + i (day offset i)."""
    offsets = np.arange(first, last + 1)
    index = pd.date_range(ts(first), ts(last), freq="D", name="date")
    return pd.DataFrame(
        {"load_total": 300.0 + offsets, "atl": 200.0 + offsets, "tsb": 100.0 + offsets}, index=index
    )


def full_dataset(n: int, seed: int = 1, *, sport: str = "run") -> pd.DataFrame:
    """A dataset shaped like `build_dataset` output with every column filled (random, independent)."""
    rng = np.random.default_rng(seed)
    index = pd.date_range(ts(0), periods=n, freq="D", name="date")
    data: dict[str, np.ndarray] = {"activity_id": np.arange(n)}
    for column in (*OUTCOMES, *predictor_columns(), *CONTROLS):
        data[column] = rng.normal(size=n)
    if sport == "bike":
        data["pace_at_ref_hr_day"] = np.full(n, np.nan)
    return pd.DataFrame(data, index=index)


def controls_frame(rng: np.random.Generator, n: int, tsb: np.ndarray | None = None) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "tsb": rng.normal(0, 10, n) if tsb is None else tsb,
            "atl_prev": rng.normal(60, 15, n),
            "load_prev": rng.normal(80, 30, n),
        }
    )


def run_correlate(x, y, controls, **kwargs) -> CorrelationResult:
    return correlate(x, y, controls, sport="run", predictor="sleep_s_lag0", outcome="ef", **kwargs)


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


# --------------------------------------------------------------------------------------------------
# vectorized helpers


def test_spearman_rows_equals_scipy_spearmanr() -> None:
    rng = np.random.default_rng(7)
    n = 60
    x = rng.integers(0, 8, n).astype(float)  # many ties
    y = x + rng.integers(0, 5, n)
    idx = rng.integers(0, n, size=(50, n))
    rho = spearman_rows(x[idx], y[idx])
    for b in range(idx.shape[0]):
        expected = stats.spearmanr(x[idx[b]], y[idx[b]]).statistic
        assert rho[b] == pytest.approx(expected, abs=1e-12)


def test_spearman_rows_constant_row_is_nan() -> None:
    a = np.array([[1.0, 1.0, 1.0, 1.0], [1.0, 2.0, 3.0, 4.0]])
    b = np.array([[1.0, 2.0, 3.0, 4.0], [4.0, 3.0, 2.0, 1.0]])
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        rho = spearman_rows(a, b)
    assert np.isnan(rho[0])
    assert rho[1] == pytest.approx(-1.0, abs=TOL)


def test_residualize_rows_matches_lstsq() -> None:
    rng = np.random.default_rng(3)
    n = 40
    c = rng.normal(size=(n, 3)) * [10.0, 50.0, 100.0] + [0.0, 60.0, 80.0]
    x = rng.normal(size=n) + 0.1 * c[:, 0]
    y = rng.normal(size=n) - 0.02 * c[:, 2]
    design = np.column_stack([np.ones(n), c])
    rx_expected = x - design @ np.linalg.lstsq(design, x, rcond=None)[0]
    ry_expected = y - design @ np.linalg.lstsq(design, y, rcond=None)[0]
    rx, ry = residualize_rows(x[None, :], y[None, :], c[None, :, :])
    np.testing.assert_allclose(rx[0], rx_expected, atol=1e-9)
    np.testing.assert_allclose(ry[0], ry_expected, atol=1e-9)


def test_quartile_contrast_rows_needs_five_per_group() -> None:
    # n = 16: Q1 sits at sorted position 3.75 → bottom = 4 rows → null
    x16 = np.arange(16.0)
    contrast, n_bottom, n_top = quartile_contrast_rows(x16[None, :], x16[None, :])
    assert np.isnan(contrast[0])
    assert (n_bottom[0], n_top[0]) == (4, 4)
    # n = 20: Q1 at position 4.75 (4.75) → bottom = x 0..4 (5 rows), top = x 15..19 (5 rows)
    x20 = np.arange(20.0)
    contrast, n_bottom, n_top = quartile_contrast_rows(x20[None, :], x20[None, :])
    assert (n_bottom[0], n_top[0]) == (5, 5)
    assert contrast[0] == pytest.approx(17.0 - 2.0, abs=TOL)


# --------------------------------------------------------------------------------------------------
# correlate


def test_raw_rho_and_p_equal_scipy() -> None:
    rng = np.random.default_rng(11)
    x = rng.normal(size=50)
    y = 0.3 * x + rng.normal(size=50)
    result = run_correlate(x, y, None)
    expected = stats.spearmanr(x, y)
    assert result.status == "ok"
    assert result.n == 50
    assert result.rho == pytest.approx(expected.statistic, abs=1e-12)
    assert result.p == pytest.approx(expected.pvalue, abs=1e-12)
    # no controls → no partial; the headline is the raw ρ
    assert result.partial_n is None
    assert result.partial_rho is None
    assert result.headline_rho == result.rho


def test_partial_equals_manual_residualization() -> None:
    rng = np.random.default_rng(12)
    n = 80
    controls = controls_frame(rng, n)
    x = rng.normal(size=n) + 0.05 * controls["tsb"].to_numpy()
    y = rng.normal(size=n) + 0.01 * controls["load_prev"].to_numpy()
    design = np.column_stack([np.ones(n), controls.to_numpy()])
    rx = x - design @ np.linalg.lstsq(design, x, rcond=None)[0]
    ry = y - design @ np.linalg.lstsq(design, y, rcond=None)[0]
    expected = stats.spearmanr(rx, ry)
    result = run_correlate(x, y, controls)
    assert result.partial_n == n
    assert result.partial_rho == pytest.approx(expected.statistic, abs=1e-9)
    assert result.partial_p == pytest.approx(expected.pvalue, abs=1e-9)
    assert result.headline_rho == result.partial_rho


def test_planted_correlation() -> None:
    rng = np.random.default_rng(42)
    n = 200
    sleep = rng.uniform(5 * H, 9 * H, n)
    ef = 1.2 + 0.1 * (sleep / H) + rng.normal(0, 0.1, n)
    result = run_correlate(pd.Series(sleep), pd.Series(ef), controls_frame(rng, n))
    assert result.n == 200
    assert result.rho > 0.5
    assert result.ci_low > 0
    assert result.ci_low <= result.rho <= result.ci_high
    assert result.partial_rho > 0.5
    assert result.partial_ci_low > 0
    assert result.uncertain is False


def test_planted_confounder() -> None:
    rng = np.random.default_rng(5)
    n = 200
    tsb = rng.normal(0, 10, n)
    sleep = 7 * H + 300 * tsb + rng.normal(0, 1000, n)  # tsb → sleep
    ef = 1.5 + 0.02 * tsb + rng.normal(0, 0.07, n)  # tsb → ef, no sleep → ef link
    result = run_correlate(sleep, ef, controls_frame(rng, n, tsb=tsb))
    assert abs(result.rho) > 0.6
    assert result.ci_low > 0
    assert abs(result.partial_rho) < 0.15
    assert result.partial_ci_low <= 0 <= result.partial_ci_high
    assert result.uncertain is True  # the headline is the partial ρ


def test_insufficient_data() -> None:
    rng = np.random.default_rng(1)
    x = rng.normal(size=40)
    y = rng.normal(size=40)
    y[:11] = np.nan  # 29 complete pairs
    result = run_correlate(x, y, controls_frame(rng, 40))
    assert result.status == "insufficient_data"
    assert result.n == 29
    assert result.partial_n == 29
    for field in (
        "rho",
        "p",
        "ci_low",
        "ci_high",
        "partial_rho",
        "partial_p",
        "partial_ci_low",
        "partial_ci_high",
        "q_contrast",
        "q_ci_low",
        "q_ci_high",
        "q_n_bottom",
        "q_n_top",
    ):
        assert getattr(result, field) is None, field
    assert result.headline_rho is None
    assert result.uncertain is True


def test_partial_n_counts_controls() -> None:
    rng = np.random.default_rng(2)
    n = 40
    x = rng.normal(size=n)
    y = x + rng.normal(size=n)
    controls = controls_frame(rng, n)
    controls.loc[:14, "atl_prev"] = np.nan  # 15 rows without a control → partial_n = 25 < 30
    result = run_correlate(x, y, controls)
    assert result.status == "ok"
    assert result.n == 40
    assert result.partial_n == 25
    assert result.partial_rho is None
    assert result.partial_ci_low is None
    assert result.headline_rho == result.rho  # falls back to the raw ρ


def test_constant_predictor_gives_null_rho() -> None:
    rng = np.random.default_rng(3)
    n = 50
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        result = run_correlate(np.full(n, 5.0), rng.normal(size=n), controls_frame(rng, n))
    assert result.status == "ok"
    assert result.n == 50
    assert result.rho is None
    assert result.p is None
    assert result.ci_low is None and result.ci_high is None
    assert result.partial_rho is None
    assert result.partial_ci_low is None
    assert result.headline_rho is None
    assert result.q_contrast is None and result.q_ci_low is None  # §9: no contrast without ρ
    assert result.uncertain is True


def test_ci_null_when_too_many_nan_resamples() -> None:
    # 39 zeros and one 1: a resample misses the 1 with probability (39/40)^40 ≈ 36 % > 10 %
    rng = np.random.default_rng(4)
    x = np.zeros(40)
    x[-1] = 1.0
    result = run_correlate(x, rng.normal(size=40), None)
    assert result.rho is not None
    assert result.ci_low is None and result.ci_high is None
    assert result.uncertain is True


def test_quartile_contrast_on_step_function() -> None:
    # x = 0..99, y = 5 for x ≥ 50 else 0. Q1 = 24.75, Q3 = 74.25 → bottom x 0..24, top x 75..99.
    # Every resample's quartiles stay on their side of 50, so the contrast is exactly 5 in all of them.
    x = np.arange(100.0)
    y = np.where(x >= 50, 5.0, 0.0)
    result = run_correlate(x, y, None)
    assert result.q_contrast == pytest.approx(5.0, abs=TOL)
    assert result.q_ci_low == pytest.approx(5.0, abs=TOL)
    assert result.q_ci_high == pytest.approx(5.0, abs=TOL)
    assert (result.q_n_bottom, result.q_n_top) == (25, 25)


def test_same_seed_is_deterministic() -> None:
    rng = np.random.default_rng(9)
    n = 60
    x = rng.normal(size=n)
    y = 0.5 * x + rng.normal(size=n)
    controls = controls_frame(rng, n)
    first = run_correlate(x, y, controls, seed=0)
    second = run_correlate(x, y, controls, seed=0)
    assert first == second
    other = run_correlate(x, y, controls, seed=1)
    assert other.rho == first.rho  # the point estimate does not depend on the seed
    assert (other.ci_low, other.ci_high) != (first.ci_low, first.ci_high)


def test_uncertain_follows_headline_ci() -> None:
    base = CorrelationResult(
        sport="run",
        predictor="sleep_s_lag0",
        outcome="ef",
        n=50,
        status="ok",
        rho=0.4,
        p=0.01,
        ci_low=0.1,
        ci_high=0.6,
        partial_n=50,
        partial_rho=None,
        partial_p=None,
        partial_ci_low=None,
        partial_ci_high=None,
        q_contrast=None,
        q_ci_low=None,
        q_ci_high=None,
        q_n_bottom=None,
        q_n_top=None,
        uncertain=False,
    )
    assert base.headline_rho == 0.4
    with_partial = replace(base, partial_rho=0.1, partial_ci_low=-0.1, partial_ci_high=0.3)
    assert with_partial.headline_rho == 0.1


# --------------------------------------------------------------------------------------------------
# correlations


def test_correlations_run_covers_all_pairs_sorted() -> None:
    ds = full_dataset(120, seed=3)
    rng = np.random.default_rng(8)
    ds["ef"] = ds["sleep_s_lag0"] + 0.5 * rng.normal(size=120)  # one strong finding
    ds["rpe_residual"] = np.nan  # an outcome without data → insufficient, sorted last
    results = correlations(ds, "run", n_boot=200)
    assert len(results) == 19 * 4
    assert {(r.predictor, r.outcome) for r in results} == {
        (p, o) for p in predictor_columns() for o in OUTCOMES
    }
    assert all(r.sport == "run" for r in results)
    assert (results[0].predictor, results[0].outcome) == ("sleep_s_lag0", "ef")
    headlines = [r.headline_rho for r in results]
    known = [abs(h) for h in headlines if h is not None]
    assert known == sorted(known, reverse=True)
    first_none = headlines.index(None)
    assert all(h is None for h in headlines[first_none:])
    assert {r.outcome for r in results[first_none:]} == {"rpe_residual"}
    assert all(r.status == "insufficient_data" for r in results[first_none:])


def test_correlations_equal_per_pair_correlate_on_sparse_data() -> None:
    """The memo shared by `correlations` must not change any number, whatever the null pattern."""
    ds = full_dataset(90, seed=6)
    rng = np.random.default_rng(10)
    for column in (*OUTCOMES, *predictor_columns(), *CONTROLS):
        ds.loc[rng.random(90) < 0.15, column] = np.nan  # a different row set for (almost) every pair
    ds["ef"] = ds["sleep_s_lag0"].fillna(0) + rng.normal(size=90)
    results = correlations(ds, "run", n_boot=150, seed=3)
    by_pair = {(r.predictor, r.outcome): r for r in results}
    for predictor in ("sleep_s_lag0", "rhr_mean3", "sleep_debt_7"):
        for outcome in OUTCOMES:
            expected = correlate(
                ds[predictor],
                ds[outcome],
                ds[list(CONTROLS)],
                sport="run",
                predictor=predictor,
                outcome=outcome,
                n_boot=150,
                seed=3,
            )
            assert by_pair[(predictor, outcome)] == expected
    assert any(r.partial_n is not None and r.partial_n < r.n for r in results)


def test_correlations_bike_has_no_pace_results() -> None:
    results = correlations(full_dataset(60, sport="bike"), "bike", n_boot=100)
    assert len(results) == 19 * 3
    assert "pace_at_ref_hr_day" not in {r.outcome for r in results}
    assert all(r.sport == "bike" for r in results)


def test_correlations_rejects_other_sport() -> None:
    with pytest.raises(ValueError):
        correlations(full_dataset(40), "other")


def test_correlations_timing_400_rows() -> None:
    """Timing: 19 predictors × 4 outcomes, 2 bootstraps of 1000 each, on 400 rows in < 10 s."""
    ds = full_dataset(400, seed=5)
    start = time.perf_counter()
    results = correlations(ds, "run")
    elapsed = time.perf_counter() - start
    assert len(results) == 76
    assert all(r.status == "ok" and r.partial_rho is not None for r in results)
    assert elapsed < 10.0, f"correlations took {elapsed:.2f} s"
