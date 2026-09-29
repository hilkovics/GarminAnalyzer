"""Grade-adjusted pace – METRICS §3.

C(i) = 155.4·i⁵ − 30.4·i⁴ − 43.3·i³ + 46.3·i² + 19.5·i + 3.6 (J/kg/m), C(0) = 3.6.
gap_speed_i = speed_i · C(grade_i) / C(0); NaN grade → gap_speed = speed.
Changed 2026-09-29: gap_speed is clamped to the run speed range of §0.4 (0–7 m/s).
"""

import numpy as np
import pytest

from training.metrics.gap import C0, gap_speed, minetti_cost
from training.metrics.preprocess import MAX_SPEED

RUN_MAX = MAX_SPEED["run"]  # §0.4 run speed range 0–7 m/s, the single source of the clamp

# Hand-computed from the §3 polynomial (term by term, exact decimals).
C_PLUS_10 = 0.001554 - 0.00304 - 0.0433 + 0.463 + 1.95 + 3.6  # 5.968214
C_MINUS_10 = -0.001554 - 0.00304 + 0.0433 + 0.463 - 1.95 + 3.6  # 2.151706
C_PLUS_30 = 0.377622 - 0.24624 - 1.1691 + 4.167 + 5.85 + 3.6  # 12.579282
C_MINUS_30 = -0.377622 - 0.24624 + 1.1691 + 4.167 - 5.85 + 3.6  # 2.462238


def gap(speed, grade) -> np.ndarray:
    return gap_speed(np.asarray(speed, dtype=float), np.asarray(grade, dtype=float), max_speed=RUN_MAX)


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
    assert np.array_equal(gap(speed, np.zeros(5)), speed)
    assert np.array_equal(gap(speed, np.full(5, -0.0)), speed)


def test_plus_ten_percent_at_2_5_mps():
    out = gap([2.5], [0.10])
    assert out[0] == pytest.approx(2.5 * 5.968214 / 3.6, abs=1e-12)
    assert out[0] == pytest.approx(4.1446, abs=1e-4)  # METRICS §3 "≈ 4.1 m/s"


def test_minus_ten_percent_is_slower_equivalent():
    out = gap([2.5], [-0.10])
    assert out[0] == pytest.approx(2.5 * 2.151706 / 3.6, abs=1e-12)


def test_nan_grade_gives_speed_nan_speed_gives_nan():
    out = gap([3.0, np.nan, np.nan], [np.nan, 0.1, np.nan])
    assert out[0] == 3.0
    assert np.isnan(out[1]) and np.isnan(out[2])


def test_shape_mismatch_rejected():
    with pytest.raises(ValueError):
        gap(np.ones(3), np.zeros(2))


# ---------------------------------------------------------------- clamp to the §0.4 run range


def test_run_max_is_the_0_4_run_limit():
    assert RUN_MAX == 7.0


def test_plus_30_percent_at_3_mps_is_clamped_to_exactly_7():
    # Unclamped: 3 · 12.579282 / 3.6 = 10.482735 m/s (C(0.30)/C(0) ≈ 3.49).
    unclamped = 3.0 * C_PLUS_30 / 3.6
    assert unclamped == pytest.approx(10.482735, abs=1e-6)
    out = gap([3.0], [0.30])
    assert out[0] == 7.0


def test_just_below_the_clamp_is_unchanged():
    out = gap([2.0], [0.30])  # 2 · 12.579282 / 3.6 = 6.988490 < 7
    assert out[0] == pytest.approx(2.0 * C_PLUS_30 / 3.6, abs=1e-12)
    assert out[0] == pytest.approx(6.988490, abs=1e-6)


def test_downhill_stays_non_negative_and_is_not_clamped():
    out = gap([0.0, 3.0, 7.0], [-0.30, -0.30, -0.30])
    np.testing.assert_allclose(out, [0.0, 3.0 * C_MINUS_30 / 3.6, 7.0 * C_MINUS_30 / 3.6], atol=1e-12)
    assert out[1] == pytest.approx(2.051865, abs=1e-6)
    assert out[2] == pytest.approx(4.787685, abs=1e-6)
    assert (out >= 0.0).all()


def test_out_of_range_speed_is_clamped_with_or_without_grade():
    out = gap([-1.0, -1.0, 9.0, 9.0], [0.0, np.nan, 0.0, np.nan])
    np.testing.assert_array_equal(out, [0.0, 0.0, 7.0, 7.0])


def test_clamp_keeps_nan():
    out = gap([np.nan, 3.0], [0.30, 0.30])
    assert np.isnan(out[0]) and out[1] == 7.0


def test_max_speed_is_required():
    with pytest.raises(TypeError):
        gap_speed(np.ones(3), np.zeros(3))  # type: ignore[call-arg]
