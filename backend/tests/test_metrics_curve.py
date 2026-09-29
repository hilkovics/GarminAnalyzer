"""Speed–HR curve – METRICS §6.1 (and the §9 single-activity `pace_at_ref_hr_day`)."""

import json

import numpy as np
import pandas as pd
import pytest

from tests.synthetic import constant, ramp, with_hr_dropout, with_pause, with_segment
from training.metrics.curve import (
    AGGREGATE_S,
    BIN_BPM,
    MIN_DAY_AGGREGATES,
    MIN_PER_BIN,
    REF_FRACTION,
    SpeedHrCurve,
    aggregates_60s,
    curve_to_json,
    hr_bin,
    pace_at_ref_hr_day,
    speed_hr_curve,
)
from training.metrics.preprocess import preprocess


def run(df: pd.DataFrame):
    return preprocess(df, "run")


def aggs(pairs: list[tuple[float, float]]) -> pd.DataFrame:
    """Aggregates from (hr, gap_speed) pairs."""
    return pd.DataFrame(pairs, columns=["hr", "gap_speed"])[["gap_speed", "hr"]]


def test_constants():
    assert (AGGREGATE_S, BIN_BPM, MIN_PER_BIN, REF_FRACTION, MIN_DAY_AGGREGATES) == (60, 5, 10, 0.80, 20)


# ---------------------------------------------------------------- 60 s aggregates


def test_aggregates_block_alignment_and_lag():
    out = aggregates_60s(run(ramp()))
    assert list(out.columns) == ["gap_speed", "hr"]
    assert len(out) == 5  # positions 600..899 (the last 30 have no lagged partner)
    k = np.arange(5)
    assert np.allclose(out["gap_speed"], 2.0 + 0.001 * (629.5 + 60 * k), rtol=0, atol=1e-9)
    assert np.allclose(out["hr"], 100 + 0.01 * (659.5 + 60 * k), rtol=0, atol=1e-9)  # partner t + 30


def test_aggregates_last_partial_block_dropped():
    assert len(aggregates_60s(run(ramp(929)))) == 4


def test_aggregates_first_600s_excluded():
    df = with_segment(constant(930, hr=150.0, speed=3.0), 0, 600, hr=120.0, speed=5.0)
    out = aggregates_60s(run(df))
    assert len(out) == 5
    assert (out["gap_speed"] == 3.0).all() and (out["hr"] == 150.0).all()


def test_aggregates_nan_block_dropped():
    # Raw HR NaN at t = 730 → lagged NaN at position 700 → block [660, 720) dropped.
    out = aggregates_60s(run(with_hr_dropout(ramp(), 730, 1)))
    assert len(out) == 4
    k = np.array([0, 2, 3, 4])
    assert np.allclose(out["gap_speed"], 2.0 + 0.001 * (629.5 + 60 * k), rtol=0, atol=1e-9)


def test_aggregates_nan_speed_drops_block():
    df = constant(930, hr=150.0, speed=3.0)
    df.loc[df["t"] == 800, "speed"] = np.nan
    assert len(aggregates_60s(run(df))) == 4


def test_aggregates_slow_samples_excluded():
    # 10 walking samples at positions 700..709 leave the sample set: 290 samples → 4 blocks, all 3.0 m/s.
    df = with_segment(constant(930, hr=150.0, speed=3.0), 700, 10, speed=0.5)
    out = aggregates_60s(run(df))
    assert len(out) == 4
    assert (out["gap_speed"] == 3.0).all()


def test_aggregates_are_over_kept_samples():
    # A 100 s pause is skipped: 1030 s with the pause → 930 kept → 5 blocks.
    out = aggregates_60s(run(with_pause(constant(1030, hr=150.0, speed=3.0), 700, 100)))
    assert len(out) == 5


def test_aggregates_empty_and_short():
    assert aggregates_60s(run(constant(629))).empty
    assert list(aggregates_60s(run(constant(10))).columns) == ["gap_speed", "hr"]


# ---------------------------------------------------------------- bins


@pytest.mark.parametrize(
    ("hr", "label"), [(144.99, 140), (145.0, 145), (149.999, 145), (150.0, 150), (136.0, 135)]
)
def test_hr_bin_floor_label(hr: float, label: int):
    assert hr_bin(hr) == label


def test_hr_bin_tolerates_float_noise_at_the_edge():
    # Summation noise just below an edge (e.g. a 60 s mean of 145-ish values) still lands in [145, 150).
    assert hr_bin(145.0 - 1e-12) == 145
    assert hr_bin(145.0 - 1e-6) == 140


def test_curve_bins_median_and_minimum():
    rows = [(146.0, 3.0 + 0.1 * i) for i in range(10)]  # bin 145, median of 10 = (3.4 + 3.5) / 2
    rows += [(151.0, 4.0)] * 9  # bin 150 has only 9 → omitted
    rows += [(155.0, 1.0), (159.99, 2.0), (157.0, 3.0)] + [(156.0, 2.5)] * 8  # bin 155, 11 values
    curve = speed_hr_curve(aggs(rows), lthr=None)
    assert isinstance(curve, SpeedHrCurve)
    assert set(curve.bins) == {145, 155}
    assert curve.bins[145] == pytest.approx(3.45)
    assert curve.bins[155] == pytest.approx(2.5)
    assert curve.counts == {145: 10, 155: 11}
    assert curve.ref_hr is None and curve.pace_at_ref_hr is None


def test_curve_ref_bin_selection():
    rows = [(136.0, 3.2)] * 10 + [(140.0, 3.5)] * 10
    curve = speed_hr_curve(aggs(rows), lthr=170.0)  # ref_hr = 136 → bin 135
    assert curve.ref_hr == pytest.approx(136.0)
    assert curve.pace_at_ref_hr == pytest.approx(3.2)
    curve = speed_hr_curve(aggs(rows), lthr=175.0)  # ref_hr = 140 → bin 140 (lower edge belongs to it)
    assert curve.pace_at_ref_hr == pytest.approx(3.5)


def test_curve_ref_fraction_configurable():
    rows = [(150.0, 3.3)] * 10
    curve = speed_hr_curve(aggs(rows), lthr=200.0, ref_fraction=0.75)  # 150
    assert curve.ref_hr == pytest.approx(150.0) and curve.pace_at_ref_hr == pytest.approx(3.3)


def test_curve_ref_bin_omitted_gives_null():
    rows = [(136.0, 3.2)] * 9 + [(140.0, 3.5)] * 10
    curve = speed_hr_curve(aggs(rows), lthr=170.0)
    assert curve.ref_hr == pytest.approx(136.0)
    assert curve.pace_at_ref_hr is None
    assert 135 not in curve.bins


def test_curve_empty():
    curve = speed_hr_curve(aggs([]), lthr=170.0)
    assert curve.bins == {} and curve.counts == {} and curve.pace_at_ref_hr is None
    assert curve.ref_hr == pytest.approx(136.0)


def test_curve_from_pooled_runs():
    # Two runs of 5 aggregates each at 150 bpm lagged → one bin 150 with 10 aggregates.
    a = aggregates_60s(run(constant(930, hr=150.0, speed=3.0)))
    b = aggregates_60s(run(constant(930, hr=150.0, speed=3.2)))
    curve = speed_hr_curve(pd.concat([a, b], ignore_index=True), lthr=187.5)  # ref 150
    assert curve.counts == {150: 10}
    assert curve.pace_at_ref_hr == pytest.approx(3.1)


def test_curve_to_json_shape():
    rows = [(146.0, 3.0)] * 10 + [(136.0, 2.8)] * 12
    data = curve_to_json(speed_hr_curve(aggs(rows), lthr=170.0))
    assert data == {
        "bins": {"135": 2.8, "145": 3.0},
        "counts": {"135": 12, "145": 10},
        "ref_hr": 136.0,
        "pace_at_ref_hr": 2.8,
    }
    assert list(data["bins"]) == ["135", "145"]  # ascending
    assert json.loads(json.dumps(data)) == data
    assert all(type(v) is float for v in data["bins"].values())
    assert all(type(v) is int for v in data["counts"].values())
    empty = curve_to_json(speed_hr_curve(aggs([]), lthr=None))
    assert empty == {"bins": {}, "counts": {}, "ref_hr": None, "pace_at_ref_hr": None}


# ---------------------------------------------------------------- §9 pace_at_ref_hr_day


def test_day_value_needs_20_in_band():
    rows = [(145.0, 3.0)] * 10 + [(155.0, 3.4)] * 9  # ref 150 → [145, 155] inclusive, 19 in band
    rows += [(144.99, 9.0), (155.01, 9.0)]  # outside
    assert pace_at_ref_hr_day(aggs(rows), 150.0) is None
    rows += [(150.0, 3.2)]  # 20 in band: median of 10 × 3.0, 3.2, 9 × 3.4 → (3.2 + 3.4) / 2... sorted
    value = pace_at_ref_hr_day(aggs(rows), 150.0)
    # sorted: 3.0 ×10, 3.2, 3.4 ×9 → middle two are the 10th and 11th: 3.0 and 3.2.
    assert value == pytest.approx(3.1)


def test_day_value_null_cases():
    assert pace_at_ref_hr_day(aggs([(150.0, 3.0)] * 30), None) is None
    assert pace_at_ref_hr_day(aggs([]), 150.0) is None


def test_day_value_from_activity():
    # 35 min at 150 bpm after the warm-up: 35 aggregates in band.
    a = aggregates_60s(run(constant(600 + 35 * 60 + 30, hr=150.0, speed=3.1)))
    assert len(a) == 35
    assert pace_at_ref_hr_day(a, 0.8 * 187.5) == pytest.approx(3.1)
