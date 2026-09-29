"""LTTB downsampling (services/lttb.py): pure numpy, known answers on synthetic series."""

import numpy as np
import pytest

from training.services.lttb import gap_markers, lttb_indices, select_indices


def wave(n: int) -> tuple[np.ndarray, np.ndarray]:
    x = np.arange(n, dtype=float)
    return x, 10 * np.sin(x / 50)


def test_keeps_first_and_last_and_returns_at_most_threshold_ascending():
    x, y = wave(5000)
    for threshold in (3, 4, 10, 100, 1500):
        idx = lttb_indices(x, y, threshold)
        assert len(idx) <= threshold
        assert idx[0] == 0 and idx[-1] == len(x) - 1
        assert (np.diff(idx) > 0).all()  # strictly ascending, so unique


def test_threshold_at_or_above_length_returns_everything():
    x, y = wave(50)
    assert lttb_indices(x, y, 50).tolist() == list(range(50))
    assert lttb_indices(x, y, 500).tolist() == list(range(50))


def test_threshold_of_exactly_the_bucket_count_is_honoured():
    x, y = wave(2000)
    assert len(lttb_indices(x, y, 100)) == 100  # one pick per bucket, every bucket is non-empty here


def test_preserves_an_upward_spike_and_a_downward_dip():
    x, y = wave(2000)
    y[1234] = 100.0
    y[321] = -100.0
    idx = lttb_indices(x, y, 60)
    assert 1234 in idx and 321 in idx
    assert y[idx].max() == 100.0 and y[idx].min() == -100.0


def test_preserves_a_step_edge():
    x = np.arange(3000, dtype=float)
    y = np.where(x < 1500, 0.0, 50.0)
    idx = lttb_indices(x, y, 30)
    assert set(y[idx]) == {0.0, 50.0}  # both levels survive, so the step is still drawn


def test_constant_series_and_minimum_threshold():
    x = np.arange(100, dtype=float)
    idx = lttb_indices(x, np.full(100, 7.0), 3)
    assert len(idx) == 3 and idx[0] == 0 and idx[-1] == 99


def test_rejects_threshold_below_three_and_mismatched_input():
    x, y = wave(100)
    with pytest.raises(ValueError):
        lttb_indices(x, y, 2)
    with pytest.raises(ValueError):
        lttb_indices(x, y[:-1], 10)


def test_uneven_x_spacing_is_respected():
    """A long pause (big x gap) must not be treated as evenly spaced samples."""
    x = np.concatenate([np.arange(500.0), np.arange(500.0) + 10_000])
    y = np.concatenate([np.zeros(500), np.full(500, 20.0)])
    idx = lttb_indices(x, y, 20)
    assert 499 in idx or 500 in idx  # a point next to the jump is kept
    assert idx[0] == 0 and idx[-1] == 999


# --- gaps and several series ------------------------------------------------------------------------------


def test_gap_markers_are_first_null_of_interior_runs_longest_first():
    valid = np.ones(30, dtype=bool)
    valid[[5, 6, 7, 20]] = False  # a run of 3 at 5, a run of 1 at 20
    valid[:2] = False  # leading nulls are not "between" valid samples
    valid[-2:] = False  # nor trailing ones
    assert gap_markers(valid, 10).tolist() == [5, 20]
    assert gap_markers(valid, 1).tolist() == [5]
    assert gap_markers(valid, 0).tolist() == []
    assert gap_markers(np.zeros(5, dtype=bool), 3).tolist() == []


def test_select_indices_returns_everything_when_short_enough():
    t = np.arange(40)
    assert select_indices(t, {"a": np.arange(40.0)}, 100).tolist() == list(range(40))


def test_select_indices_budget_is_shared_and_extremes_of_every_series_survive():
    t = np.arange(3000)
    hr = 150 + 5 * np.sin(t / 80)
    speed = 3 + 0.3 * np.cos(t / 40)
    alt = 100 + t / 30
    hr[700] = 210.0
    speed[2100] = 0.0
    idx = select_indices(t, {"hr": hr, "speed": speed, "alt": alt}, 300)
    assert len(idx) <= 300
    assert idx[0] == 0 and idx[-1] == 2999
    assert 700 in idx and 2100 in idx
    assert (np.diff(idx) > 0).all()


def test_select_indices_keeps_a_marker_inside_a_gap_so_charts_break_the_line():
    t = np.arange(2000)
    hr = 150 + 10 * np.sin(t / 30)
    hr[400:450] = np.nan
    idx = select_indices(t, {"hr": hr}, 100)
    assert len(idx) <= 100
    null_picks = idx[np.isnan(hr[idx])]
    assert null_picks.tolist() == [400]  # exactly one break marker, no other null samples


def test_select_indices_ignores_series_without_values_and_never_exceeds_points():
    t = np.arange(1000)
    empty = np.full(1000, np.nan)
    flapping = np.where(t % 4 == 0, np.nan, np.sin(t / 10))  # 250 one-sample gaps
    idx = select_indices(t, {"alt": empty, "hr": flapping}, 60)
    assert len(idx) <= 60
    assert idx[0] == 0 and idx[-1] == 999
    only_empty = select_indices(t, {"alt": empty}, 60)
    assert only_empty.tolist() == [0, 999]


def test_select_indices_with_more_series_than_points_allow_still_caps_the_total():
    t = np.arange(500)
    series = {f"s{i}": np.sin(t / (5 + i)) for i in range(8)}
    idx = select_indices(t, series, 10)
    assert len(idx) <= 10 and idx[0] == 0 and idx[-1] == 499


def test_select_indices_rejects_too_few_points():
    with pytest.raises(ValueError):
        select_indices(np.arange(10), {"a": np.arange(10.0)}, 2)
