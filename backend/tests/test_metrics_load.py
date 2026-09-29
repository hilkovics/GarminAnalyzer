"""Training load – METRICS §2 (hrTSS §2.1, TRIMP §2.2, rTSS §2.3, sanity check §2.5)."""

import math

import numpy as np
import pandas as pd
import pytest

from tests.synthetic import constant, intervals
from training.metrics.load import (
    IF_TABLE,
    LoadSanity,
    activity_if_hr,
    hrtss,
    intensity_factor_hr,
    load_sanity,
    normalized_graded_speed,
    rtss,
    trimp,
    trimp_norm,
    usable_gps,
)

# ---------------------------------------------------------------- §2.1 IF table / hrTSS


def test_if_table_verbatim():
    assert IF_TABLE == (
        (0.50, 0.30),
        (0.68, 0.55),
        (0.83, 0.75),
        (0.94, 0.90),
        (1.00, 1.00),
        (1.05, 1.05),
        (1.15, 1.20),
    )


@pytest.mark.parametrize(("r", "expected"), IF_TABLE)
def test_if_at_table_points_is_exact(r, expected):
    assert intensity_factor_hr(np.array([r]))[0] == expected


@pytest.mark.parametrize(
    ("r", "expected"),
    [
        (0.59, (0.30 + 0.55) / 2),
        (0.755, (0.55 + 0.75) / 2),
        (0.885, (0.75 + 0.90) / 2),
        (0.97, (0.90 + 1.00) / 2),
        (1.025, (1.00 + 1.05) / 2),
        (1.10, (1.05 + 1.20) / 2),
    ],
)
def test_if_interpolation_midpoints(r, expected):
    assert intensity_factor_hr(np.array([r]))[0] == pytest.approx(expected, abs=1e-12)


@pytest.mark.parametrize(
    ("r", "expected"), [(0.0, 0.30), (0.3, 0.30), (0.4999, 0.30), (1.1501, 1.20), (2.0, 1.20)]
)
def test_if_clamps_r_to_0_50_and_1_15(r, expected):
    assert intensity_factor_hr(np.array([r]))[0] == expected


def test_if_nan_stays_nan():
    out = intensity_factor_hr(np.array([np.nan, 1.0]))
    assert np.isnan(out[0]) and out[1] == 1.0


def test_hrtss_one_hour_at_lthr_is_100():
    hr = constant(3600, hr=170.0)["hr"].to_numpy()
    assert hrtss(hr, 170.0) == pytest.approx(100.0, abs=1e-9)
    assert activity_if_hr(hrtss(hr, 170.0), 3600) == pytest.approx(1.0, abs=1e-12)


def test_hrtss_one_hour_at_r_0_83_is_56_25():
    hr = constant(3600, hr=166.0)["hr"].to_numpy()  # 166 / 200 = 0.83 → IF 0.75
    assert hrtss(hr, 200.0) == pytest.approx(56.25, abs=1e-9)
    assert activity_if_hr(56.25, 3600) == pytest.approx(0.75, abs=1e-12)


def test_hrtss_clamped_below_and_above():
    assert hrtss(np.full(3600, 60.0), 200.0) == pytest.approx(0.30**2 * 100, abs=1e-9)  # r = 0.3 → IF 0.30
    assert hrtss(np.full(3600, 195.0), 150.0) == pytest.approx(1.20**2 * 100, abs=1e-9)  # r = 1.3 → IF 1.20


def test_hrtss_nan_samples_contribute_zero():
    hr = np.r_[np.full(1800, 170.0), np.full(1800, np.nan)]
    assert hrtss(hr, 170.0) == pytest.approx(50.0, abs=1e-9)
    assert activity_if_hr(50.0, 3600) == pytest.approx(math.sqrt(0.5), abs=1e-12)


def test_hrtss_without_any_valid_hr_is_none():
    """METRICS §2.1 changed 2026-09-29: no valid HR sample → hrTSS and IF_hr null (unknown), not 0."""
    assert hrtss(np.full(10, np.nan), 170.0) is None
    assert hrtss(np.array([]), 170.0) is None
    assert activity_if_hr(None, 3600) is None
    assert activity_if_hr(None, 0) is None


def test_hrtss_one_valid_sample_is_a_small_number():
    hr = np.r_[[170.0], np.full(3599, np.nan)]  # one second at lthr → IF 1.0
    assert hrtss(hr, 170.0) == pytest.approx(1 / 36, abs=1e-15)
    assert activity_if_hr(1 / 36, 3600) == pytest.approx(1 / 60, abs=1e-15)


def test_hrtss_intervals():
    hr = intervals()["hr"].to_numpy()  # 1800 s at r = 1.05, 1800 s at r = 0.83
    assert hrtss(hr, 200.0) == pytest.approx(83.25, abs=1e-9)
    assert activity_if_hr(83.25, 3600) == pytest.approx(math.sqrt(0.8325), abs=1e-12)


def test_activity_if_hr_without_moving_time_is_none():
    assert activity_if_hr(0.0, 0) is None


@pytest.mark.parametrize("lthr", [0.0, -170.0, np.nan])
def test_hrtss_rejects_bad_lthr(lthr):
    with pytest.raises(ValueError):
        hrtss(np.full(10, 150.0), lthr)


# ---------------------------------------------------------------- §2.2 TRIMP

REST, MAX, LTHR = 50.0, 190.0, 162.0  # HRr at lthr = 112 / 140 = 0.8


def test_trimp_male_constants():
    got = trimp(np.full(3600, LTHR), REST, MAX, "male")
    assert got == pytest.approx(60 * 0.8 * 0.64 * math.exp(1.92 * 0.8), abs=1e-9)
    assert got == pytest.approx(142.724173115, abs=1e-8)


def test_trimp_female_constants():
    got = trimp(np.full(3600, LTHR), REST, MAX, "female")
    assert got == pytest.approx(60 * 0.8 * 0.86 * math.exp(1.67 * 0.8), abs=1e-9)
    assert got == pytest.approx(157.020774959, abs=1e-8)


def test_trimp_hrr_clamped_to_0_1():
    assert trimp(np.full(600, 45.0), REST, MAX, "male") == 0.0  # valid HR below rest → HRr 0 (a real 0)
    above = trimp(np.full(3600, 200.0), REST, MAX, "male")  # above max → HRr 1
    assert above == pytest.approx(60 * 0.64 * math.exp(1.92), abs=1e-9)
    assert trimp(np.full(3600, 200.0), REST, MAX, "female") == pytest.approx(
        60 * 0.86 * math.exp(1.67), abs=1e-9
    )


def test_trimp_nan_samples_skipped():
    hr = np.r_[np.full(1800, LTHR), np.full(1800, np.nan)]
    assert trimp(hr, REST, MAX, "male") == pytest.approx(30 * 0.8 * 0.64 * math.exp(1.92 * 0.8), abs=1e-9)


@pytest.mark.parametrize("sex", ["male", "female"])
def test_trimp_without_any_valid_hr_is_none(sex):
    """METRICS §2.1 changed 2026-09-29: no valid HR sample → TRIMP and TRIMP_norm null, not 0."""
    assert trimp(np.full(600, np.nan), REST, MAX, sex) is None
    assert trimp(np.array([]), REST, MAX, sex) is None
    assert trimp_norm(None, rest_hr=REST, max_hr=MAX, lthr=LTHR, sex=sex) is None


def test_trimp_without_hr_still_validates_parameters():
    with pytest.raises(ValueError):
        trimp(np.full(10, np.nan), REST, MAX, "x")
    with pytest.raises(ValueError):
        trimp(np.full(10, np.nan), REST, REST, "male")  # max_hr ≤ rest_hr


def test_trimp_one_valid_sample_is_a_small_number():
    hr = np.r_[[LTHR], np.full(3599, np.nan)]  # one second at HRr 0.8
    value = trimp(hr, REST, MAX, "male")
    assert value == pytest.approx(0.8 * 0.64 * math.exp(1.92 * 0.8) / 60, abs=1e-12)
    # One of the 3600 reference seconds → 100 / 3600.
    got = trimp_norm(value, rest_hr=REST, max_hr=MAX, lthr=LTHR, sex="male")
    assert got == pytest.approx(100 / 3600, abs=1e-12)


@pytest.mark.parametrize("sex", ["male", "female"])
def test_trimp_norm_60_min_at_lthr_is_100(sex):
    value = trimp(np.full(3600, LTHR), REST, MAX, sex)
    assert trimp_norm(value, rest_hr=REST, max_hr=MAX, lthr=LTHR, sex=sex) == pytest.approx(100.0, abs=1e-9)


def test_trimp_norm_30_min_at_lthr_is_50():
    value = trimp(np.full(1800, LTHR), REST, MAX, "male")
    assert trimp_norm(value, rest_hr=REST, max_hr=MAX, lthr=LTHR, sex="male") == pytest.approx(50.0, abs=1e-9)


def test_trimp_norm_at_max_hr_male():
    value = trimp(np.full(3600, MAX), REST, MAX, "male")
    got = trimp_norm(value, rest_hr=REST, max_hr=MAX, lthr=LTHR, sex="male")
    # 100 · (1 · e^1.92) / (0.8 · e^(1.92·0.8)) = 100 · e^0.384 / 0.8
    assert got == pytest.approx(100 * math.exp(1.92 * 0.2) / 0.8, abs=1e-9)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"sex": "x"},
        {"max_hr": 50.0},  # max_hr ≤ rest_hr
        {"max_hr": 40.0},
    ],
)
def test_trimp_rejects_bad_parameters(kwargs):
    args = {"rest_hr": REST, "max_hr": MAX, "sex": "male"} | kwargs
    with pytest.raises(ValueError):
        trimp(np.full(10, 150.0), args["rest_hr"], args["max_hr"], args["sex"])


def test_trimp_norm_rejects_lthr_at_or_below_rest():
    with pytest.raises(ValueError):  # TRIMP_ref would be 0
        trimp_norm(10.0, rest_hr=REST, max_hr=MAX, lthr=REST, sex="male")


# ---------------------------------------------------------------- §2.3 NGS / rTSS / usable GPS


def test_ngs_constant_equals_speed():
    assert normalized_graded_speed(np.full(3600, 3.2)) == pytest.approx(3.2, abs=1e-12)


def test_ngs_two_blocks_hand_computed():
    # 60 s at 2 m/s then 60 s at 4 m/s. Trailing 30-sample windows end at i = 29..119 (91 windows):
    # 31 windows of 2, 31 of 4, and 29 mixed ones with mean 2 + k/15 (k = 1..29).
    gap = np.r_[np.full(60, 2.0), np.full(60, 4.0)]
    fourth = 31 * 2.0**4 + 31 * 4.0**4 + sum((2 + k / 15) ** 4 for k in range(1, 30))
    assert normalized_graded_speed(gap) == pytest.approx((fourth / 91) ** 0.25, abs=1e-12)


def test_ngs_at_least_mean_for_variable_pace():
    gap = intervals()["speed"].to_numpy()  # 4 / 2 m/s blocks, mean 3.0
    ngs = normalized_graded_speed(gap)
    assert ngs is not None
    assert ngs > gap.mean() == 3.0


def test_ngs_needs_30_full_windows():
    assert normalized_graded_speed(np.full(58, 3.0)) is None  # 29 windows
    assert normalized_graded_speed(np.full(59, 3.0)) == pytest.approx(3.0)  # 30 windows
    assert normalized_graded_speed(np.array([])) is None


def test_ngs_skips_windows_with_nan():
    gap = np.full(88, 3.0)  # 59 windows ...
    gap[44] = np.nan  # ... of which the 30 ending at i = 44..73 contain the NaN → 29 valid
    assert normalized_graded_speed(gap) is None
    gap = np.r_[np.full(40, 2.0), [np.nan], np.full(200, 4.0)]
    # Windows ending at 29..39 are all-2 (11), windows containing index 40 (ending 40..69) are skipped,
    # windows ending at 70..240 are all-4 (171).
    expected = ((11 * 2.0**4 + 171 * 4.0**4) / 182) ** 0.25
    assert normalized_graded_speed(gap) == pytest.approx(expected, abs=1e-12)


def test_rtss_one_hour_at_threshold_is_100():
    got = rtss(np.full(3600, 3.2), 3600, 3.2)
    assert got is not None
    value, if_pace = got
    assert value == pytest.approx(100.0, abs=1e-9)
    assert if_pace == pytest.approx(1.0, abs=1e-12)


def test_rtss_scales_with_if_squared_and_moving_s():
    value, if_pace = rtss(np.full(3600, 0.9 * 4.0), 3600, 4.0)
    assert if_pace == pytest.approx(0.9, abs=1e-12)
    assert value == pytest.approx(81.0, abs=1e-9)
    value, _ = rtss(np.full(3600, 4.0), 1800, 4.0)  # moving_s is taken as given (§2.3)
    assert value == pytest.approx(50.0, abs=1e-9)


def test_rtss_none_without_enough_windows():
    assert rtss(np.full(58, 3.0), 58, 3.0) is None


@pytest.mark.parametrize("ts", [0.0, -3.0, np.nan])
def test_rtss_rejects_bad_threshold_speed(ts):
    with pytest.raises(ValueError):
        rtss(np.full(100, 3.0), 100, ts)


def _gps_frame(n: int, n_speed: int, *, distance: bool = True) -> pd.DataFrame:
    speed = np.r_[np.full(n_speed, 3.0), np.full(n - n_speed, np.nan)]
    dist = np.arange(n, dtype=float) * 3.0 if distance else np.full(n, np.nan)
    return pd.DataFrame({"speed": speed, "distance": dist})


def test_usable_gps_rules():
    assert usable_gps(_gps_frame(1000, 1000), is_indoor=False)
    assert usable_gps(_gps_frame(1000, 900), is_indoor=False)  # exactly 90 %
    assert not usable_gps(_gps_frame(1000, 899), is_indoor=False)
    assert not usable_gps(_gps_frame(1000, 1000), is_indoor=True)
    assert not usable_gps(_gps_frame(1000, 1000, distance=False), is_indoor=False)
    one_distance = _gps_frame(1000, 1000, distance=False)
    one_distance.loc[500, "distance"] = 1500.0  # "present" = at least one non-NaN value
    assert usable_gps(one_distance, is_indoor=False)
    assert not usable_gps(_gps_frame(0, 0), is_indoor=False)


# ---------------------------------------------------------------- §2.5 sanity check


def test_load_sanity_good_perfect_correlation():
    s = load_sanity([10, 20, 30, 40], [1, 2, 3, 4])
    assert s == LoadSanity(r=pytest.approx(1.0, abs=1e-12), n=4, status="good")


@pytest.mark.parametrize(
    ("y", "r", "status"),
    [
        ([1, 2, 3, 5, 4], 0.9, "good"),
        ([1, 3, 2, 4, 5], 0.9, "good"),
        ([1, 4, 2, 3, 5], 0.7, "fair"),  # 0.7 is inside "fair"
        ([3, 1, 2, 5, 4], 0.6, "warning"),
        ([5, 4, 3, 2, 1], -1.0, "warning"),
    ],
)
def test_load_sanity_bands(y, r, status):
    s = load_sanity([1, 2, 3, 4, 5], y)
    assert s.r == pytest.approx(r, abs=1e-12)
    assert s.n == 5
    assert s.status == status


def test_load_sanity_r_exactly_0_8_is_fair():
    s = load_sanity([1, 2, 3, 4], [1, 3, 2, 4])  # Σdxdy = 4, Σdx² = Σdy² = 5 → r = 0.8
    assert s.r == pytest.approx(0.8, abs=1e-12)
    assert s.status == "fair"


def test_load_sanity_drops_pairs_with_missing_side():
    s = load_sanity([1, None, 2, 3, np.nan, 4], [1, 5, 2, 3, 7, None])
    assert s.n == 3
    assert s.r == pytest.approx(1.0, abs=1e-12)


def test_load_sanity_insufficient():
    assert load_sanity([1, 2], [1, 2]) == LoadSanity(r=None, n=2, status="insufficient")
    assert load_sanity([1, 2, None], [1, 2, 3]) == LoadSanity(r=None, n=2, status="insufficient")
    assert load_sanity([], []) == LoadSanity(r=None, n=0, status="insufficient")


def test_load_sanity_zero_variance_has_no_r():
    assert load_sanity([5, 5, 5], [1, 2, 3]) == LoadSanity(r=None, n=3, status="insufficient")


def test_load_sanity_length_mismatch():
    with pytest.raises(ValueError):
        load_sanity([1, 2, 3], [1, 2])


def test_load_sanity_constant_side_with_float_residue_is_insufficient():
    """Review phase 2 nit: a constant series must not yield a garbage r from float residue."""
    from training.metrics.load import load_sanity

    out = load_sanity([33.3, 33.3, 33.3, 33.3], [10.0, 20.0, 30.0, 40.0])
    assert out.r is None and out.status == "insufficient"
