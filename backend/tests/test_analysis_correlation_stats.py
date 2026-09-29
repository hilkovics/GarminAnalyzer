"""METRICS §9: vectorized statistics, correlate() and correlations()."""

import time
import warnings
from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from training.analysis.correlation import (
    CONTROLS,
    OUTCOMES,
    CorrelationResult,
    correlate,
    correlations,
    predictor_columns,
)
from training.analysis.stats import quartile_contrast_rows, residualize_rows, spearman_rows

from .correlation_seeding import (
    TOL,
    H,
    controls_frame,
    full_dataset,
    run_correlate,
)

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
    """Timing: 19 predictors × 4 outcomes, 2 bootstraps of 1000 each, on 400 rows in < 30 s."""
    ds = full_dataset(400, seed=5)
    start = time.perf_counter()
    results = correlations(ds, "run")
    elapsed = time.perf_counter() - start
    assert len(results) == 76
    assert all(r.status == "ok" and r.partial_rho is not None for r in results)
    assert elapsed < 30.0, f"correlations took {elapsed:.2f} s"  # ~3 s locally; generous for slow CI
