"""Grade-adjusted pace – METRICS §3.

C(i) = 155.4·i⁵ − 30.4·i⁴ − 43.3·i³ + 46.3·i² + 19.5·i + 3.6 (J/kg/m), C(0) = 3.6.
gap_speed_i = speed_i · C(grade_i) / C(0); NaN grade → gap_speed = speed.
"""

import numpy as np
import pytest

from training.metrics.gap import C0, gap_speed, minetti_cost

# Hand-computed from the §3 polynomial (term by term, exact decimals).
C_PLUS_10 = 0.001554 - 0.00304 - 0.0433 + 0.463 + 1.95 + 3.6  # 5.968214
C_MINUS_10 = -0.001554 - 0.00304 + 0.0433 + 0.463 - 1.95 + 3.6  # 2.151706
C_PLUS_30 = 0.377622 - 0.24624 - 1.1691 + 4.167 + 5.85 + 3.6  # 12.579282
C_MINUS_30 = -0.377622 - 0.24624 + 1.1691 + 4.167 - 5.85 + 3.6  # 2.462238


def test_c0_is_3_6():
    assert C0 == 3.6
    assert minetti_cost(np.array([0.0]))[0] == 3.6


@pytest.mark.parametrize(
    ("grade", "expected"),
    [(0.10, 5.968214), (-0.10, 2.151706), (0.30, 12.579282), (-0.30, 2.462238)],
)
def test_minetti_cost_values(grade, expected):
    assert minetti_cost(np.array([grade]))[0] == pytest.approx(expected, abs=1e-12)


def test_hand_constants_match_decimal_values():
    assert pytest.approx(5.968214, abs=1e-12) == C_PLUS_10
    assert pytest.approx(2.151706, abs=1e-12) == C_MINUS_10
    assert pytest.approx(12.579282, abs=1e-12) == C_PLUS_30
    assert pytest.approx(2.462238, abs=1e-12) == C_MINUS_30


def test_minetti_cost_nan_passes_through():
    out = minetti_cost(np.array([np.nan, 0.05]))
    assert np.isnan(out[0]) and not np.isnan(out[1])


def test_flat_gap_equals_speed_exactly():
    speed = np.array([0.0, 1.0, 2.5, 3.33, 7.0])
    assert np.array_equal(gap_speed(speed, np.zeros(5)), speed)
    assert np.array_equal(gap_speed(speed, np.full(5, -0.0)), speed)


def test_plus_ten_percent_at_2_5_mps():
    out = gap_speed(np.array([2.5]), np.array([0.10]))
    assert out[0] == pytest.approx(2.5 * 5.968214 / 3.6, abs=1e-12)
    assert out[0] == pytest.approx(4.1446, abs=1e-4)  # METRICS §3 "≈ 4.1 m/s"


def test_minus_ten_percent_is_slower_equivalent():
    out = gap_speed(np.array([2.5]), np.array([-0.10]))
    assert out[0] == pytest.approx(2.5 * 2.151706 / 3.6, abs=1e-12)


def test_nan_grade_gives_speed_nan_speed_gives_nan():
    out = gap_speed(np.array([3.0, np.nan, np.nan]), np.array([np.nan, 0.1, np.nan]))
    assert out[0] == 3.0
    assert np.isnan(out[1]) and np.isnan(out[2])


def test_shape_mismatch_rejected():
    with pytest.raises(ValueError):
        gap_speed(np.ones(3), np.zeros(2))
