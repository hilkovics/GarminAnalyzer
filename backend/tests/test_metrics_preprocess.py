"""Stream preprocessing – METRICS §0.2–§0.6 (§0.1 and the §0.4 speed derivation happen in normalize/)."""

import numpy as np
import pandas as pd
import pytest

from tests.synthetic import constant, hilly, stream, with_hr_dropout, with_pause
from training.metrics.gap import minetti_cost
from training.metrics.preprocess import SAMPLE_COLUMNS, Preprocessed, lag_hr, preprocess
from training.normalize.streams import empty_streams

# ---------------------------------------------------------------- shape, §0.2 kept samples


def test_output_columns_and_dtypes():
    pre = preprocess(constant(100), "run")
    assert isinstance(pre, Preprocessed)
    assert SAMPLE_COLUMNS == ("t", "hr", "speed", "alt", "grade", "distance", "gap_speed", "is_slow")
    assert list(pre.samples.columns) == list(SAMPLE_COLUMNS)
    assert pre.samples["t"].dtype == np.int64
    assert pre.samples["is_slow"].dtype == bool
    for col in ("hr", "speed", "alt", "grade", "distance", "gap_speed"):
        assert pre.samples[col].dtype == np.float64, col
    assert pre.samples.index.tolist() == list(range(100))


def test_paused_samples_removed_and_moving_s_counts_kept():
    df = with_pause(constant(4200, hr=170.0), 1800, 600, hr=200.0, alt=5000.0)
    pre = preprocess(df, "run")
    assert pre.moving_s == 3600
    assert len(pre.samples) == 3600
    t = pre.samples["t"].to_numpy()
    assert not ((t >= 1800) & (t < 2400)).any()
    assert (pre.samples["hr"] == 170.0).all()  # the paused HR of 200 is gone
    assert (pre.samples["alt"] == 100.0).all()  # the paused altitude never enters the median


def test_rows_sorted_by_time():
    df = hilly(200)
    shuffled = df.sample(frac=1.0, random_state=1)
    pd.testing.assert_frame_equal(preprocess(shuffled, "run").samples, preprocess(df, "run").samples)


def test_empty_streams():
    pre = preprocess(empty_streams(), "run")
    assert pre.moving_s == 0
    assert pre.hr_coverage == 0.0
    assert pre.low_confidence is True
    assert list(pre.samples.columns) == list(SAMPLE_COLUMNS)
    assert pre.samples.empty


def test_all_paused_is_empty():
    pre = preprocess(stream(hr=150.0, speed=3.0, moving=False, n=50), "bike")
    assert pre.moving_s == 0 and pre.hr_coverage == 0.0 and pre.low_confidence


def test_invalid_sport_rejected():
    with pytest.raises(ValueError):
        preprocess(constant(10), "swim")


def test_missing_columns_rejected():
    with pytest.raises(ValueError, match="alt"):
        preprocess(constant(10).drop(columns=["alt"]), "run")


def test_db_style_none_values_are_nan():
    df = constant(20).astype({"hr": object, "alt": object})
    df.loc[3, "hr"] = None
    df["alt"] = None  # an all-NULL column arrives as object dtype
    pre = preprocess(df, "run")
    assert np.isnan(pre.samples.loc[3, "hr"])
    assert pre.samples["alt"].isna().all()
    assert pre.samples["grade"].isna().all()


# ---------------------------------------------------------------- §0.3 HR validity / coverage


def test_hr_validity_bounds_inclusive():
    hr = [39.0, 39.9, 40.0, 150.0, 230.0, 230.5, 231.0, np.nan, 0.0, -5.0]
    pre = preprocess(stream(hr=hr, speed=3.0), "run")
    expected = [np.nan, np.nan, 40.0, 150.0, 230.0, np.nan, np.nan, np.nan, np.nan, np.nan]
    np.testing.assert_array_equal(pre.samples["hr"].to_numpy(), expected)
    assert pre.hr_coverage == pytest.approx(0.3)


@pytest.mark.parametrize(("valid", "low"), [(70, False), (69, True), (100, False), (0, True)])
def test_coverage_and_low_confidence_at_0_70(valid, low):
    hr = np.r_[np.full(valid, 150.0), np.full(100 - valid, np.nan)]
    pre = preprocess(stream(hr=hr, speed=3.0), "run")
    assert pre.hr_coverage == valid / 100
    assert pre.low_confidence is low


def test_coverage_over_kept_samples_only():
    # 100 kept samples, 70 with HR, plus 50 paused samples that all have HR.
    hr = np.r_[np.full(70, 150.0), np.full(30, np.nan), np.full(50, 150.0)]
    moving = np.r_[np.ones(100, bool), np.zeros(50, bool)]
    pre = preprocess(stream(hr=hr, speed=3.0, moving=moving), "run")
    assert pre.moving_s == 100
    assert pre.hr_coverage == 0.70
    assert pre.low_confidence is False


def test_dropout_coverage():
    pre = preprocess(with_hr_dropout(constant(3600, hr=170.0), 600, 900), "run")
    assert pre.hr_coverage == 0.75
    assert pre.samples["hr"].isna().sum() == 900


# ---------------------------------------------------------------- §0.4 speed clamp / slow flag


@pytest.mark.parametrize(
    ("sport", "speed", "expected"),
    [
        ("run", [-1.0, 0.0, 3.0, 7.0, 8.0, np.nan], [0.0, 0.0, 3.0, 7.0, 7.0, np.nan]),
        ("other", [-1.0, 7.5, 12.0], [0.0, 7.0, 7.0]),  # other uses the run limits
        ("bike", [-0.1, 8.0, 25.0, 30.0], [0.0, 8.0, 25.0, 25.0]),
    ],
)
def test_speed_clamped_not_dropped(sport, speed, expected):
    pre = preprocess(stream(hr=150.0, speed=speed, distance=np.nan), sport)
    assert len(pre.samples) == len(speed)
    np.testing.assert_array_equal(pre.samples["speed"].to_numpy(), expected)


@pytest.mark.parametrize(
    ("sport", "speed", "slow"),
    [
        ("run", [0.0, 0.99, 1.0, 3.0, np.nan], [True, True, False, False, False]),
        ("other", [0.99, 1.0, 1.99], [True, False, False]),
        ("bike", [0.0, 1.0, 1.99, 2.0, 10.0], [True, True, True, False, False]),
    ],
)
def test_slow_flag(sport, speed, slow):
    pre = preprocess(stream(hr=150.0, speed=speed, distance=np.nan), sport)
    assert pre.samples["is_slow"].tolist() == slow


def test_slow_samples_are_kept():
    pre = preprocess(stream(hr=150.0, speed=[0.5] * 10 + [3.0] * 10), "run")
    assert pre.moving_s == 20
    assert pre.samples["is_slow"].sum() == 10


# ---------------------------------------------------------------- §0.5 altitude median


def test_altitude_median_window_5_min_3():
    alt = [10.0, 20.0, np.nan, 40.0, 50.0, np.nan, np.nan, np.nan, 90.0, 100.0]
    pre = preprocess(stream(hr=150.0, speed=3.0, alt=alt), "run")
    # i=0 [10,20,–] 2 values; i=1 {10,20,40} → 20; i=2 {10,20,40,50} → 30; i=3 {20,40,50} → 40; rest < 3.
    expected = [np.nan, 20.0, 30.0, 40.0, np.nan, np.nan, np.nan, np.nan, np.nan, np.nan]
    np.testing.assert_array_equal(pre.samples["alt"].to_numpy(), expected)


def test_altitude_median_removes_short_spikes():
    alt = np.full(30, 100.0)
    alt[10:12] = [150.0, 160.0]
    pre = preprocess(stream(hr=150.0, speed=3.0, alt=alt), "run")
    assert (pre.samples["alt"] == 100.0).all()


def test_altitude_median_skips_pause_instead_of_bridging():
    # Kept samples have alt = kept index (0..19); the 4 paused samples in between have alt 1000.
    moving = np.r_[np.ones(8, bool), np.zeros(4, bool), np.ones(12, bool)]
    alt = np.r_[np.arange(8.0), np.full(4, 1000.0), np.arange(8.0, 20.0)]
    pre = preprocess(stream(hr=150.0, speed=3.0, alt=alt, moving=moving), "run")
    smoothed = pre.samples["alt"].to_numpy()
    np.testing.assert_array_equal(smoothed[2:18], np.arange(2.0, 18.0))  # linear → centre value


# ---------------------------------------------------------------- §0.5 grade


def test_grade_constant_slope_interior():
    pre = preprocess(hilly(600, speed=2.5, grade=0.10), "run")
    g = pre.samples["grade"].to_numpy()
    np.testing.assert_allclose(g[7:-7], 0.10, atol=1e-12)
    # Clipped windows at the ends see the median-shifted end altitudes (see synthetic.hilly).
    assert g[0] == pytest.approx(0.8 * 0.10, abs=1e-12)
    assert g[5] == pytest.approx(0.9 * 0.10, abs=1e-12)
    assert g[6] == pytest.approx(0.95 * 0.10, abs=1e-12)


def test_grade_window_is_i_minus_5_to_i_plus_5():
    # Flat at 0 m, a 3 m step at sample 50 (a median keeps the step): Δalt = 3 exactly when
    # i − 5 < 50 ≤ i + 5, i.e. i = 45..54, over Δdist = 30 m → 0.1.
    alt = np.r_[np.zeros(50), np.full(50, 3.0)]
    pre = preprocess(stream(hr=150.0, speed=3.0, alt=alt), "run")
    expected = np.zeros(100)
    expected[45:55] = 0.1
    np.testing.assert_allclose(pre.samples["grade"].to_numpy(), expected, atol=1e-12)


@pytest.mark.parametrize(("grade", "clamped"), [(0.5, 0.30), (-0.5, -0.30), (0.30, 0.30), (-0.29, -0.29)])
def test_grade_clamped_to_0_30(grade, clamped):
    pre = preprocess(hilly(100, speed=3.0, grade=grade), "run")
    np.testing.assert_allclose(pre.samples["grade"].to_numpy()[7:-7], clamped, atol=1e-12)


def test_grade_nan_below_5_m_and_clipped_at_ends():
    # 0.5 m/s: interior Δdist = 10 · 0.5 = 5.0 m (valid, the bound is inclusive); the clipped windows of
    # samples 0..4 and n−5..n−1 span 2.5..4.5 m → NaN.
    pre = preprocess(stream(hr=150.0, speed=0.5, alt=100.0, n=40), "run")
    g = pre.samples["grade"].to_numpy()
    assert np.isnan(g[:5]).all() and np.isnan(g[-5:]).all()
    np.testing.assert_array_equal(g[5:-5], 0.0)
    pre = preprocess(stream(hr=150.0, speed=0.45, alt=100.0, n=40), "run")  # Δdist ≤ 4.5 m everywhere
    assert pre.samples["grade"].isna().all()


def test_grade_nan_when_window_end_missing():
    df = constant(60)
    df.loc[20, "distance"] = np.nan
    g = preprocess(df, "run").samples["grade"].to_numpy()
    assert np.isnan(g[15]) and np.isnan(g[25])  # they use sample 20 as i + 5 / i − 5
    assert g[20] == 0.0  # sample 20 itself uses 15 and 25
    assert np.isnan(g).sum() == 2


def test_grade_across_pause_uses_kept_neighbours():
    # 20 kept at +10 % (0.25 m per sample at 2.5 m/s), a 30 s pause, 20 more kept at the same slope.
    df = with_pause(hilly(70, speed=2.5, grade=0.10), 20, 30)
    kept = df[df["moving"]]
    df.loc[kept.index, "alt"] = 100.0 + 0.10 * kept["distance"]  # slope continues along kept distance
    g = preprocess(df, "run").samples["grade"].to_numpy()
    np.testing.assert_allclose(g[7:-7], 0.10, atol=1e-12)


def test_grade_nan_without_distance():
    df = constant(60)
    df["distance"] = np.nan
    assert preprocess(df, "run").samples["grade"].isna().all()


# ---------------------------------------------------------------- §3 GAP in preprocess


def test_gap_speed_runs_use_grade():
    pre = preprocess(hilly(600, speed=2.5, grade=0.10), "run")
    gap = pre.samples["gap_speed"].to_numpy()
    np.testing.assert_allclose(gap[7:-7], 2.5 * 5.968214 / 3.6, atol=1e-12)
    np.testing.assert_allclose(gap, 2.5 * minetti_cost(pre.samples["grade"].to_numpy()) / 3.6, atol=1e-12)


def test_gap_speed_flat_run_equals_speed():
    pre = preprocess(constant(600, speed=3.3), "run")
    np.testing.assert_array_equal(pre.samples["gap_speed"].to_numpy(), pre.samples["speed"].to_numpy())


@pytest.mark.parametrize("sport", ["bike", "other"])
def test_gap_speed_is_speed_for_non_runs(sport):
    pre = preprocess(hilly(600, speed=2.5, grade=0.10), sport)
    assert pre.samples["grade"].notna().any()
    np.testing.assert_array_equal(pre.samples["gap_speed"].to_numpy(), pre.samples["speed"].to_numpy())


def test_gap_speed_nan_grade_falls_back_to_clamped_speed():
    df = stream(hr=150.0, speed=[9.0] * 10, distance=np.nan)
    pre = preprocess(df, "run")
    np.testing.assert_array_equal(pre.samples["gap_speed"].to_numpy(), 7.0)


# ---------------------------------------------------------------- §0.6 HR lag helper


def test_lag_hr_pairs_speed_t_with_hr_t_plus_lag():
    hr = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    np.testing.assert_array_equal(lag_hr(hr, 2), [3.0, 4.0, 5.0, np.nan, np.nan])
    np.testing.assert_array_equal(lag_hr(hr, 0), hr)
    np.testing.assert_array_equal(lag_hr(hr, 7), [np.nan] * 5)


def test_lag_hr_default_30_s():
    hr = np.arange(100, dtype=float)
    out = lag_hr(hr)
    assert out[0] == 30.0 and out[69] == 99.0
    assert np.isnan(out[70:]).all()


def test_lag_hr_negative_shifts_forward():
    np.testing.assert_array_equal(lag_hr(np.array([1.0, 2.0, 3.0]), -1), [np.nan, 1.0, 2.0])


def test_lag_hr_does_not_modify_input():
    hr = np.array([1.0, 2.0, 3.0])
    lag_hr(hr, 1)
    np.testing.assert_array_equal(hr, [1.0, 2.0, 3.0])
