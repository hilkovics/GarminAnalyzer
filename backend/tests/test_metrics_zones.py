"""HR and pace zones, time in zone – METRICS §1.

HR:   Z1 r < 0.68, Z2 0.68 ≤ r < 0.84, Z3 0.84 ≤ r < 0.95, Z4 0.95 ≤ r ≤ 1.05, Z5 r > 1.05 (r = hr / lthr).
Pace: Z1 s < 0.78, Z2 0.78 ≤ s < 0.88, Z3 0.88 ≤ s < 0.95, Z4 0.95 ≤ s ≤ 1.05, Z5 s > 1.05.
"""

import numpy as np
import pytest

from tests.synthetic import constant, hr_ramp, intervals
from training.metrics.zones import (
    HR_ZONE_BOUNDS,
    PACE_ZONE_BOUNDS,
    default_zones,
    time_in_zones,
    zone_of,
)


def test_bounds_are_the_spec_values():
    assert HR_ZONE_BOUNDS == (0.68, 0.84, 0.95, 1.05)
    assert PACE_ZONE_BOUNDS == (0.78, 0.88, 0.95, 1.05)


def test_default_zones_json_shape_and_fresh_copy():
    z = default_zones()
    assert z == {"hr": [0.68, 0.84, 0.95, 1.05], "pace": [0.78, 0.88, 0.95, 1.05]}
    z["hr"][0] = 0.1
    assert default_zones()["hr"][0] == 0.68


@pytest.mark.parametrize(
    ("r", "zone"),
    [
        (0.0, 1),
        (np.nextafter(0.68, 0), 1),
        (0.68, 2),  # inclusive lower edge of Z2
        (0.835, 2),  # the old gap between 0.83 and 0.84
        (np.nextafter(0.84, 0), 2),
        (0.84, 3),
        (0.945, 3),  # the old gap between 0.94 and 0.95
        (np.nextafter(0.95, 0), 3),
        (0.95, 4),
        (1.0, 4),
        (1.05, 4),  # Z4 is closed at both ends
        (np.nextafter(1.05, 2), 5),
        (2.0, 5),
    ],
)
def test_hr_zone_edges(r, zone):
    assert zone_of(np.array([r]), HR_ZONE_BOUNDS)[0] == zone


@pytest.mark.parametrize(
    ("s", "zone"),
    [
        (np.nextafter(0.78, 0), 1),
        (0.78, 2),
        (np.nextafter(0.88, 0), 2),
        (0.88, 3),
        (np.nextafter(0.95, 0), 3),
        (0.95, 4),
        (1.05, 4),
        (np.nextafter(1.05, 2), 5),
    ],
)
def test_pace_zone_edges(s, zone):
    assert zone_of(np.array([s]), PACE_ZONE_BOUNDS)[0] == zone


def test_zone_of_nan_is_zero_and_dtype_int():
    out = zone_of(np.array([np.nan, 1.0, np.nan]), HR_ZONE_BOUNDS)
    assert out.tolist() == [0, 4, 0]
    assert np.issubdtype(out.dtype, np.integer)


@pytest.mark.parametrize("bounds", [(0.68, 0.84, 0.95), (0.84, 0.68, 0.95, 1.05), (0.7, 0.8, 0.9, np.nan)])
def test_zone_of_rejects_bad_bounds(bounds):
    with pytest.raises(ValueError):
        zone_of(np.array([1.0]), bounds)


def test_time_in_zones_integer_bpm_at_every_edge():
    # lthr = 200 puts every HR bound on a whole bpm: 136, 168, 190, 210.
    hr = np.array([135, 136, 167, 168, 189, 190, 210, 211, np.nan], dtype=float)
    tiz = time_in_zones(hr, 200.0, HR_ZONE_BOUNDS)
    assert tiz == {"1": 1, "2": 2, "3": 2, "4": 2, "5": 1}
    assert sum(tiz.values()) == 8  # NaN not counted
    assert all(type(v) is int for v in tiz.values())


def test_time_in_zones_pace_edges():
    # threshold_speed = 4.0 m/s: bounds at 3.12, 3.52, 3.80, 4.20 m/s.
    speed = np.array([3.11, 3.12, 3.51, 3.52, 3.79, 3.80, 4.20, 4.21, 0.0])
    tiz = time_in_zones(speed, 4.0, PACE_ZONE_BOUNDS)
    assert tiz == {"1": 2, "2": 2, "3": 2, "4": 2, "5": 1}  # stopped (0 m/s) falls into Z1


def test_time_in_zones_all_keys_present_even_if_empty():
    assert time_in_zones(np.array([np.nan, np.nan]), 170.0, HR_ZONE_BOUNDS) == {
        "1": 0,
        "2": 0,
        "3": 0,
        "4": 0,
        "5": 0,
    }
    assert time_in_zones(np.array([]), 170.0, HR_ZONE_BOUNDS) == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}


def test_time_in_zones_constant_at_lthr_is_all_z4():
    df = constant(3600, hr=170.0)
    assert time_in_zones(df["hr"].to_numpy(), 170.0, HR_ZONE_BOUNDS) == {
        "1": 0,
        "2": 0,
        "3": 0,
        "4": 3600,
        "5": 0,
    }


def test_time_in_zones_hr_ramp():
    df = hr_ramp()  # 100..219 bpm, 120 s
    tiz = time_in_zones(df["hr"].to_numpy(), 200.0, HR_ZONE_BOUNDS)
    assert tiz == {"1": 36, "2": 32, "3": 22, "4": 21, "5": 9}
    assert sum(tiz.values()) == 120


def test_time_in_zones_intervals():
    df = intervals()
    tiz = time_in_zones(df["hr"].to_numpy(), 200.0, HR_ZONE_BOUNDS)
    assert tiz == {"1": 0, "2": 1800, "3": 0, "4": 1800, "5": 0}


def test_time_in_zones_custom_bounds():
    hr = np.array([100.0, 120.0, 140.0, 160.0, 180.0])
    assert time_in_zones(hr, 200.0, [0.55, 0.65, 0.75, 0.85]) == {"1": 1, "2": 1, "3": 1, "4": 1, "5": 1}


@pytest.mark.parametrize("threshold", [0.0, -1.0, np.nan])
def test_time_in_zones_rejects_bad_threshold(threshold):
    with pytest.raises(ValueError):
        time_in_zones(np.array([150.0]), threshold, HR_ZONE_BOUNDS)
