"""Steady state, EF, aerobic decoupling – METRICS §5.1–§5.4 (with the §0.6 HR lag)."""

from functools import partial

import numpy as np
import pytest

from tests.synthetic import (
    block_hr,
    constant,
    flat_then_climb,
    hilly,
    hr_drift,
    speed_hr_step,
    with_hr_dropout,
    with_pause,
    with_segment,
)
from training.metrics.efficiency import (
    EfficiencyResult,
    decoupling_band,
    ef_samples,
    efficiency,
    is_steady_state,
)
from training.metrics.gap import minetti_cost
from training.metrics.preprocess import preprocess

run = partial(preprocess, sport="run")
bike = partial(preprocess, sport="bike")


# ---------------------------------------------------------------- §5.1 steady state


def test_steady_constant_exactly_1800_after_warmup():
    assert is_steady_state(run(constant(2400, hr=150.0)), 180.0) is True


def test_not_steady_with_1799_after_warmup():
    assert is_steady_state(run(constant(2399, hr=150.0)), 180.0) is False


def test_moving_s_counts_kept_samples_only():
    # 2500 s with a 100 s pause → 2400 kept → 1800 after the first 600.
    assert is_steady_state(run(with_pause(constant(2500, hr=150.0), 1000, 100)), 180.0) is True
    assert is_steady_state(run(with_pause(constant(2500, hr=150.0), 1000, 101)), 180.0) is False


def test_no_lthr_is_not_steady():
    assert is_steady_state(run(constant(3600, hr=150.0)), None) is False


def test_warmup_is_dropped():
    # 600 s at 200 bpm (> 0.95 · 180 = 171, and far outside the band) – ignored.
    df = with_segment(constant(2400, hr=150.0), 0, 600, hr=200.0, speed=2.0)
    assert is_steady_state(run(df), 180.0) is True
    # 660 s of it: the first 60 samples after the warm-up form a ≥ 60 s stretch above 171.
    df = with_segment(constant(2400, hr=150.0), 0, 660, hr=200.0)
    assert is_steady_state(run(df), 180.0) is False


@pytest.mark.parametrize(("dropout", "steady"), [(180, True), (181, False)])
def test_hr_coverage_edge_0_9(dropout: int, steady: bool):
    # 1620 / 1800 = 0.9 exactly → steady; 1619 / 1800 → not. The whole-activity coverage is higher.
    df = with_hr_dropout(constant(2400, hr=150.0), 1000, dropout)
    assert is_steady_state(run(df), 180.0) is steady


@pytest.mark.parametrize(("hr", "steady"), [(140.0, True), (139.9, False), (176.0, True), (176.1, False)])
def test_mean_hr_band_edges(hr: float, steady: bool):
    # lthr 200 → band [140, 176] inclusive; 0.95 · lthr = 190 is never reached.
    assert is_steady_state(run(constant(2400, hr=hr)), 200.0) is steady


def test_mean_hr_band_uses_only_after_warmup():
    df = with_segment(constant(2400, hr=150.0), 0, 600, hr=100.0)
    assert is_steady_state(run(df), 200.0) is True  # 150 in [140, 176]; with the warm-up it would be 137.5


@pytest.mark.parametrize(("amplitude", "steady"), [(5.95, True), (6.0, False)])
def test_std_of_60s_means_population_under_6(amplitude: float, steady: bool):
    # Population std of the 30 block means == amplitude (sample std of 5.95 would be 6.05 → not steady).
    assert is_steady_state(run(block_hr(2400, base=150.0, amplitude=amplitude)), 200.0) is steady


def test_std_blocks_aligned_after_warmup():
    # ±20 bpm blocks on the 60 s grid starting at 600 → std 20 → not steady. Shifted by 30 s, every block
    # mean is 150 except the first ((150 + 170) / 2 = 160) → std = 10 · sqrt(29) / 30 ≈ 1.8 → steady.
    assert is_steady_state(run(block_hr(2400, amplitude=20.0, start=600)), 200.0) is False
    assert is_steady_state(run(block_hr(2400, amplitude=20.0, start=630)), 200.0) is True


def test_last_partial_block_dropped():
    # 1830 samples after the warm-up: 30 full blocks at 150 plus a partial block of 30 at 100.
    df = with_segment(constant(2430, hr=150.0), 2400, 30, hr=100.0)
    assert is_steady_state(run(df), 200.0) is True  # mean 149.2 in band, std of full blocks 0


@pytest.mark.parametrize(("nan_in_block", "steady"), [(31, True), (30, False)])
def test_blocks_with_fewer_than_30_valid_hr_skipped(nan_in_block: int, steady: bool):
    # Block [1200, 1260): the valid samples are 190 bpm (not > 0.95 · 200). 29 valid → block skipped,
    # std 0; 30 valid → block mean 190 counts → std = 40 · sqrt(29) / 30 ≈ 7.18 → not steady.
    df = with_segment(constant(2400, hr=150.0), 1200 + nan_in_block, 60 - nan_in_block, hr=190.0)
    df = with_hr_dropout(df, 1200, nan_in_block)
    assert is_steady_state(run(df), 200.0) is steady


@pytest.mark.parametrize(("length", "steady"), [(59, True), (60, False)])
def test_stretch_above_0_95_lthr(length: int, steady: bool):
    # lthr 200 → limit 190 (strict >). Base 170 keeps the block std below 6 (≈ 3.77 for one block at 191).
    df = with_segment(constant(2400, hr=170.0), 1200, length, hr=191.0)
    assert is_steady_state(run(df), 200.0) is steady
    df = with_segment(constant(2400, hr=170.0), 1200, 120, hr=190.0)  # == limit does not count
    assert is_steady_state(run(df), 200.0) is True


def test_nan_breaks_the_stretch():
    df = with_segment(constant(2400, hr=170.0), 1200, 61, hr=191.0)
    assert is_steady_state(run(df), 200.0) is False
    assert is_steady_state(run(with_hr_dropout(df, 1230, 1)), 200.0) is True  # 30 + NaN + 30


def test_pause_does_not_break_the_stretch():
    # Consecutive kept samples: 30 s at 191, a pause, 30 s at 191 → a 60-sample stretch.
    df = with_segment(constant(2500, hr=170.0), 1200, 130, hr=191.0)
    df = with_pause(df, 1230, 70)
    assert is_steady_state(run(df), 200.0) is False


def test_steady_state_uses_raw_hr_without_lag():
    # The last 60 kept samples at 191: with the §0.6 lag the final 30 would have no partner (only a
    # 30-sample stretch left); on raw HR it is a 60 s stretch → not steady.
    df = with_segment(constant(2400, hr=170.0), 2340, 60, hr=191.0)
    assert is_steady_state(run(df), 200.0) is False


def test_steady_state_ignores_slow_samples():
    # Walking is not dropped by §5.1 (only by EF): mean HR still counts the walking HR.
    df = with_segment(constant(2400, hr=150.0), 1200, 600, hr=100.0, speed=0.5)
    assert is_steady_state(run(df), 200.0) is False  # mean (1200·150 + 600·100) / 1800 = 133.3 < 140


# ---------------------------------------------------------------- §0.6 lag, EF sample set


def test_lag_pairs_speed_with_hr_30s_later():
    samples = ef_samples(run(speed_hr_step()), sport="run")
    assert list(samples.columns) == ["t", "speed", "hr"]
    row = samples.set_index("t")
    assert (row.loc[1199, "speed"], row.loc[1199, "hr"]) == (3.0, 150.0)
    assert (row.loc[1200, "speed"], row.loc[1200, "hr"]) == (3.1, 155.0)
    ratios = samples["speed"] / samples["hr"]
    assert np.allclose(ratios, 0.02, rtol=0, atol=1e-15)


def test_ef_sample_set_bounds():
    # 2430 kept: positions 600..2399 (the last 30 have no lagged partner).
    samples = ef_samples(run(constant(2430, hr=150.0)), sport="run")
    assert samples["t"].tolist() == list(range(600, 2400))


def test_lag_is_by_time_and_never_bridges_a_pause():
    # Pause at [1500, 1600). By time, t = 1470..1499 have no partner (the pause lies in (t, t + 30]);
    # positionally t = 1499 used to pair with t = 1629 (160 bpm), which now pairs with nothing.
    df = constant(2530, hr=150.0)
    df.loc[df["t"] == 1629, "hr"] = 160.0
    samples = ef_samples(run(with_pause(df, 1500, 100)), sport="run").set_index("t")
    assert samples.index.intersection(range(1470, 1500)).empty
    assert samples.loc[1469, "hr"] == 150.0 and samples.loc[1600, "hr"] == 150.0
    assert (samples["hr"] == 150.0).all()


def test_ef_10s_pause_recovered_hr_not_paired():
    # 10 s pause at [1500, 1510), HR 180 for 30 s after it. The kept samples t = 1480..1499 have a kept
    # sample at t + 30 (1510..1529, 180 bpm) but the pause lies in between → no partner. EF set: 1830
    # after the warm-up − 30 before the pause − the last 30 = 1770, all at 3.0 m/s / 150 bpm.
    df = with_segment(constant(2440, hr=150.0, speed=3.0), 1510, 30, hr=180.0)
    res = efficiency(run(with_pause(df, 1500, 10)), sport="run", lthr=200.0)
    assert res.steady_state is True
    assert res.n_samples == 1770
    assert res.ef == pytest.approx(1.2, rel=1e-12)
    assert res.decoupling_pct == pytest.approx(0.0, abs=1e-9)


def test_ef_samples_drop_slow_and_invalid_pairs():
    df = with_segment(constant(2430, hr=150.0), 1000, 50, speed=0.5)  # 50 walking samples
    df = with_hr_dropout(df, 1500, 20)  # lagged NaN at positions 1470..1489
    samples = ef_samples(run(df), sport="run")
    assert len(samples) == 1800 - 50 - 20
    t = samples["t"].to_numpy()
    assert not ((t >= 1000) & (t < 1050)).any()
    assert not ((t >= 1470) & (t < 1490)).any()


def test_ef_samples_other_is_empty():
    assert ef_samples(preprocess(constant(2430), "other"), sport="other").empty


# ---------------------------------------------------------------- §5.2 EF


def test_ef_constant_after_warmup_is_1_2():
    df = with_segment(constant(2430, hr=150.0, speed=3.0), 0, 600, hr=120.0, speed=2.0)
    res = efficiency(run(df), sport="run", lthr=180.0)
    assert isinstance(res, EfficiencyResult)
    assert res.steady_state is True
    assert res.ef == pytest.approx(1.2, rel=1e-12)  # 3.0 · 60 / 150
    assert res.n_samples == 1800
    assert res.decoupling_pct == pytest.approx(0.0, abs=1e-9)
    assert res.decoupling_band == "good"


def test_ef_with_speed_step_and_lagged_hr_is_1_2():
    res = efficiency(run(speed_hr_step()), sport="run", lthr=180.0)
    assert res.steady_state is True
    assert res.ef == pytest.approx(1.2, rel=1e-12)
    assert res.decoupling_pct == pytest.approx(0.0, abs=1e-9)


def test_ef_uses_gap_speed_for_runs():
    # Constant +10 % grade at 2.5 m/s: gap = 2.5 · C(0.10) / 3.6 on every sample of the EF set.
    res = efficiency(run(hilly(2430, speed=2.5, grade=0.10, hr=150.0)), sport="run", lthr=180.0)
    gap = 2.5 * float(minetti_cost(np.array(0.10))) / 3.6
    assert res.ef == pytest.approx(gap * 60 / 150, rel=1e-9)
    assert res.ef == pytest.approx(4.144593 * 60 / 150, rel=1e-6)


def test_ef_ignores_walking_samples():
    df = with_segment(constant(2430, hr=150.0), 1000, 50, speed=0.5)
    res = efficiency(run(df), sport="run", lthr=180.0)
    assert res.ef == pytest.approx(1.2, rel=1e-12)
    assert res.n_samples == 1750


def test_not_steady_gives_no_ef_but_counts_samples():
    res = efficiency(run(constant(2430, hr=150.0)), sport="run", lthr=None)
    assert res == EfficiencyResult(
        steady_state=False, ef=None, decoupling_pct=None, decoupling_band=None, n_samples=1800
    )


def test_steady_without_ef_samples_gives_none():
    # Walking the whole time: steady (HR only) but no EF sample.
    res = efficiency(run(constant(2430, hr=150.0, speed=0.5)), sport="run", lthr=180.0)
    assert res.steady_state is True
    assert (res.ef, res.decoupling_pct, res.decoupling_band, res.n_samples) == (None, None, None, 0)


def test_other_sport_steady_state_only():
    res = efficiency(preprocess(constant(2430, hr=150.0), "other"), sport="other", lthr=180.0)
    assert res == EfficiencyResult(
        steady_state=True, ef=None, decoupling_pct=None, decoupling_band=None, n_samples=0
    )


def test_invalid_sport_rejected():
    with pytest.raises(ValueError):
        efficiency(run(constant(2430)), sport="swim", lthr=180.0)


# ---------------------------------------------------------------- §5.3 decoupling


def test_decoupling_of_linear_drift():
    res = efficiency(run(hr_drift()), sport="run", lthr=180.0)
    assert res.steady_state is True
    assert res.n_samples == 3000
    # EF1 = 180 / 151.87375, EF2 = 180 / 155.62375 → (EF1 − EF2) / EF1 = 1 − 151.87375 / 155.62375.
    assert res.decoupling_pct == pytest.approx(100 * 3.75 / 155.62375, rel=1e-9)
    assert res.decoupling_pct == pytest.approx(2.40966, abs=1e-5)
    assert res.decoupling_band == "good"


def test_decoupling_step_is_moderate():
    # EF set positions 600..2399; lagged HR 150 for the first 900, 157.5 for the rest → 1 − 150 / 157.5.
    df = with_segment(constant(2430, hr=150.0), 1530, 900, hr=157.5)
    res = efficiency(run(df), sport="run", lthr=180.0)
    assert res.decoupling_pct == pytest.approx(100 * (1 - 150 / 157.5), rel=1e-12)  # 4.7619 %
    assert res.decoupling_band == "good"
    df = with_segment(constant(2430, hr=150.0), 1530, 900, hr=160.0)
    res = efficiency(run(df), sport="run", lthr=180.0)
    assert res.decoupling_pct == pytest.approx(100 * (1 - 150 / 160), rel=1e-12)  # 6.25 %
    assert res.decoupling_band == "moderate"


def test_decoupling_halves_by_sample_count_odd():
    # 601 EF samples: first ⌊601/2⌋ = 300 at 150 bpm, the other 301 at 160 bpm.
    df = with_segment(constant(2430, hr=150.0), 1200, 1230, speed=0.5)  # EF set = positions 600..1199
    df = with_segment(df, 1200, 1, speed=3.0)  # plus position 1200 → 601 samples
    df = with_segment(df, 930, 1300, hr=160.0)  # lagged HR 160 from position 900 on
    res = efficiency(run(df), sport="run", lthr=200.0)
    assert res.n_samples == 601
    assert res.decoupling_pct == pytest.approx(100 * (1 - 150 / 160), rel=1e-12)


@pytest.mark.parametrize(("walk_from", "n", "has_decoupling"), [(1199, 599, False), (1200, 600, True)])
def test_decoupling_needs_600_samples(walk_from: int, n: int, has_decoupling: bool):
    df = with_segment(constant(2430, hr=150.0), walk_from, 2430 - walk_from, speed=0.5)
    res = efficiency(run(df), sport="run", lthr=180.0)
    assert res.steady_state is True
    assert res.n_samples == n
    assert res.ef == pytest.approx(1.2, rel=1e-12)
    assert (res.decoupling_pct is not None) is has_decoupling
    assert (res.decoupling_band is not None) is has_decoupling


def test_decoupling_band_edges():
    cases = {-3.0: "good", 0.0: "good", 4.999: "good", 5.0: "moderate", 10.0: "moderate", 10.001: "poor"}
    assert {pct: decoupling_band(pct) for pct in cases} == cases
    assert decoupling_band(None) is None


# ---------------------------------------------------------------- §5.4 bike


def test_bike_ef_flat_constant():
    res = efficiency(bike(constant(2430, hr=140.0, speed=8.0)), sport="bike", lthr=170.0)
    assert res.steady_state is True
    assert res.n_samples == 1800
    assert res.ef == pytest.approx(8.0 * 60 / 140, rel=1e-12)
    assert res.decoupling_band == "good"


def test_bike_grade_filter():
    # Grade ≤ 0.01 up to t = 1500, above after → EF set positions 600..1500.
    res = efficiency(bike(flat_then_climb()), sport="bike", lthr=170.0)
    assert res.n_samples == 901
    assert res.ef == pytest.approx(8.0 * 60 / 140, rel=1e-12)


def test_bike_nan_grade_excluded():
    df = constant(2430, hr=140.0, speed=8.0)
    df["distance"] = np.nan  # no distance → grade NaN everywhere
    res = efficiency(bike(df), sport="bike", lthr=170.0)
    assert res.steady_state is True and res.n_samples == 0 and res.ef is None


def test_bike_speed_at_least_4():
    df = with_segment(constant(2430, hr=140.0, speed=8.0), 1000, 100, speed=3.99)
    df = with_segment(df, 1500, 100, speed=4.0)
    res = efficiency(bike(df), sport="bike", lthr=170.0)
    assert res.n_samples == 1700
    assert ef_samples(bike(df), sport="bike")["speed"].min() == 4.0


def test_bike_excludes_30s_around_slow_sample():
    # A slow sample (< 2 m/s) at t = 1500 excludes t in [1470, 1530] (61 samples).
    df = with_segment(constant(2430, hr=140.0, speed=8.0), 1500, 1, speed=1.0)
    samples = ef_samples(bike(df), sport="bike")
    assert len(samples) == 1800 - 61
    t = set(samples["t"])
    assert {1469, 1531} <= t and not t & set(range(1470, 1531))


def test_bike_excludes_30s_around_pause():
    # Paused seconds 1500..1599: kept samples 1470..1499 and 1600..1629 are within 30 s of them.
    df = with_pause(constant(2530, hr=140.0, speed=8.0), 1500, 100)
    samples = ef_samples(bike(df), sport="bike")
    t = set(samples["t"])
    assert len(samples) == 1800 - 60
    assert {1469, 1630} <= t and not t & (set(range(1470, 1500)) | set(range(1600, 1630)))


def test_bike_not_steady_gives_no_ef():
    res = efficiency(bike(constant(2430, hr=140.0, speed=8.0)), sport="bike", lthr=None)
    assert res.steady_state is False and res.ef is None and res.n_samples == 1800
