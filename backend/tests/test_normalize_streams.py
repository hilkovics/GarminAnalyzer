"""normalize_streams: descriptor-key mapping, 1 s resampling, gap fill, moving flag (METRICS §0.1/§0.2/§0.4).

The synthetic `activity_run_details.json` has 120 samples at
t = 0..59 (1 s), 62, 65, 68 (3 s), 72 (4 s), 77 (5 s), 92 (15 s gap), 93..110, a pause at 113, 118, 123,
128, 129 (sumDuration stays 110, speed 0) and 130..160 with sumDuration = t − 19.
HR = 120 + t // 4, speed 3.0 m/s while running, sumDistance = 3 · sumDuration, elevation = 150 + 0.05 t.
"""

import copy
import json
import random
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest

from training.normalize.streams import MAX_FFILL_GAP_S, STREAM_COLUMNS, normalize_streams

SYNTHETIC = Path(__file__).parent / "fixtures" / "synthetic"
T0_MS = 1_789_880_400_000  # 2026-09-20T05:00:00Z


def load(name: str) -> dict[str, Any]:
    return json.loads((SYNTHETIC / name).read_text())


def build_details(samples: list[dict[str, float | None]], keys: list[str] | None = None) -> dict[str, Any]:
    """Garmin-shaped details from per-sample dicts; metricsIndex follows `keys` (default: first sample)."""
    keys = keys or list(samples[0])
    return {
        "metricDescriptors": [{"metricsIndex": i, "key": k} for i, k in enumerate(keys)],
        "activityDetailMetrics": [{"metrics": [s.get(k) for k in keys]} for s in samples],
    }


def sample(t: float, **values: float | None) -> dict[str, float | None]:
    return {"directTimestamp": T0_MS + t * 1000, **values}


@pytest.fixture(scope="module")
def run_df() -> pd.DataFrame:
    return normalize_streams(load("activity_run_details.json"))


def test_columns_dtypes_and_one_second_grid(run_df):
    assert list(run_df.columns) == STREAM_COLUMNS
    assert run_df["t"].dtype == np.int64
    assert run_df["moving"].dtype == bool
    assert (run_df["t"].to_numpy() == np.arange(161)).all()
    assert run_df["grade"].isna().all() and run_df["gap_speed"].isna().all()


def test_values_mapped_by_descriptor_key(run_df):
    at = run_df.set_index("t")
    assert at.loc[0, "hr"] == 120.0
    assert at.loc[100, "hr"] == 145.0
    assert at.loc[100, "alt"] == pytest.approx(155.0)
    assert at.loc[100, "cadence"] == 172.0
    assert at.loc[100, "lon"] == 20.0
    assert at.loc[100, "lat"] == pytest.approx(10.0 + 300.0 / 111195.0, abs=1e-7)
    assert at.loc[160, "distance"] == 423.0  # 3 m · 141 s of timer time
    assert at.loc[160, "speed"] == 3.0


def test_short_gaps_forward_filled(run_df):
    at = run_df.set_index("t")
    assert list(at.loc[59:62, "hr"]) == [134.0, 134.0, 134.0, 135.0]
    assert list(at.loc[72:77, "distance"]) == [216.0] * 5 + [231.0]
    assert at.loc[76, "alt"] == at.loc[72, "alt"]


def test_long_gap_stays_nan_but_is_moving(run_df):
    at = run_df.set_index("t")
    gap = at.loc[78:91]
    assert len(gap) == 14
    for col in ("hr", "speed", "alt", "cadence", "lat", "lon", "distance"):
        assert gap[col].isna().all(), col
    assert gap["moving"].all()  # sumDuration rose by 15 s over the 15 s gap
    assert run_df["hr"].isna().sum() == 14
    assert at.loc[77, "hr"] == 139.0 and at.loc[92, "hr"] == 143.0


def test_pause_marks_not_moving(run_df):
    paused = run_df.loc[~run_df["moving"], "t"].tolist()
    assert paused == list(range(111, 130))
    assert int(run_df["moving"].sum()) == 142  # 1 (first sample) + 141 s of timer increase
    assert (run_df.loc[run_df["t"].between(113, 129), "speed"] == 0.0).all()


def test_descriptor_order_independence():
    """Shuffling metricsIndex (and the descriptor list) must not change the result."""
    details = load("activity_run_details.json")
    reference = normalize_streams(details)
    rng = random.Random(7)
    for _ in range(3):
        shuffled = copy.deepcopy(details)
        descriptors = shuffled["metricDescriptors"]
        n = len(descriptors)
        new_pos = list(range(n))
        rng.shuffle(new_pos)
        for row in shuffled["activityDetailMetrics"]:
            old = row["metrics"]
            row["metrics"] = [None] * n
            for i, value in enumerate(old):
                row["metrics"][new_pos[i]] = value
        for d in descriptors:
            d["metricsIndex"] = new_pos[d["metricsIndex"]]
        rng.shuffle(descriptors)
        pd.testing.assert_frame_equal(normalize_streams(shuffled), reference)


def _drop_descriptor(details: dict[str, Any], key: str) -> dict[str, Any]:
    out = copy.deepcopy(details)
    out["metricDescriptors"] = [d for d in out["metricDescriptors"] if d["key"] != key]
    return out


def test_speed_derived_from_distance_when_channel_missing(run_df):
    df = normalize_streams(_drop_descriptor(load("activity_run_details.json"), "directSpeed"))
    expected = np.full(161, 3.0)
    expected[0] = np.nan  # no previous sample
    expected[78:93] = np.nan  # the whole 15 s gap (77, 92] incl. its closing sample (METRICS §0.4 note)
    expected[111:130] = 0.0  # timer (and distance) constant during the pause
    np.testing.assert_allclose(df["speed"].to_numpy(), expected, equal_nan=True)
    pd.testing.assert_frame_equal(df.drop(columns="speed"), run_df.drop(columns="speed"))


def test_speed_derived_when_channel_all_null():
    details = build_details(
        [sample(0, directSpeed=None, sumDistance=0.0), sample(2, directSpeed=None, sumDistance=5.0)]
    )
    df = normalize_streams(details)
    np.testing.assert_allclose(df["speed"], [np.nan, 2.5, 2.5], equal_nan=True)


def test_same_second_last_sample_wins():
    details = build_details(
        [
            sample(0, directHeartRate=100.0),
            sample(1, directHeartRate=110.0),
            sample(1.5, directHeartRate=120.0),
            sample(2, directHeartRate=130.0),
        ]
    )
    df = normalize_streams(details)
    assert df["t"].tolist() == [0, 1, 2]
    assert df["hr"].tolist() == [100.0, 120.0, 130.0]


def test_unsorted_samples_are_ordered_by_time():
    details = build_details([sample(2, directHeartRate=130.0), sample(0, directHeartRate=100.0)])
    df = normalize_streams(details)
    assert df["t"].tolist() == [0, 1, 2]
    assert df["hr"].tolist() == [100.0, 100.0, 130.0]


def test_ffill_boundary_at_ten_seconds():
    assert MAX_FFILL_GAP_S == 10
    filled = normalize_streams(
        build_details([sample(0, directHeartRate=100.0), sample(10, directHeartRate=150.0)])
    )
    assert filled["hr"].tolist() == [100.0] * 10 + [150.0]
    unfilled = normalize_streams(
        build_details([sample(0, directHeartRate=100.0), sample(11, directHeartRate=150.0)])
    )
    assert unfilled["hr"].iloc[0] == 100.0 and unfilled["hr"].iloc[11] == 150.0
    assert unfilled["hr"].iloc[1:11].isna().all()


def test_null_values_inside_a_channel_follow_the_same_gap_rule():
    """METRICS §0.1: a dropout inside a channel is a gap too (valid → valid ≤ 10 s is forward-filled)."""
    short = [sample(0, directHeartRate=100.0)] + [sample(t, directHeartRate=None) for t in range(1, 10)]
    short.append(sample(10, directHeartRate=110.0))
    assert normalize_streams(build_details(short))["hr"].tolist() == [100.0] * 10 + [110.0]
    long = [sample(0, directHeartRate=100.0)] + [sample(t, directHeartRate=None) for t in range(1, 11)]
    long.append(sample(11, directHeartRate=110.0))
    hr = normalize_streams(build_details(long))["hr"]
    assert hr.iloc[0] == 100.0 and hr.iloc[11] == 110.0 and hr.iloc[1:11].isna().all()
    trailing = [
        sample(0, directHeartRate=100.0),
        sample(1, directHeartRate=None),
        sample(2, directHeartRate=None),
    ]
    np.testing.assert_allclose(
        normalize_streams(build_details(trailing))["hr"], [100.0, np.nan, np.nan], equal_nan=True
    )


@pytest.mark.parametrize(
    ("delta", "expected_running"),
    [(2.0, 2), (2.4, 2), (2.5, 3), (2.6, 3), (5.0, 5), (7.0, 5), (0.0, 0), (-3.0, 0)],
)
def test_moving_splits_gap_by_timer_increase(delta, expected_running):
    details = build_details([sample(0, sumDuration=100.0), sample(5, sumDuration=100.0 + delta)])
    moving = normalize_streams(details)["moving"].tolist()
    # running seconds are the last ones of the gap, so the resume sample b (t = 5) runs whenever Δ > 0
    assert moving == [True] + [False] * (5 - expected_running) + [True] * expected_running


def test_moving_all_true_without_timer_channel():
    details = build_details([sample(0, directHeartRate=100.0), sample(30, directHeartRate=110.0)])
    df = normalize_streams(details)
    assert len(df) == 31 and df["moving"].all()


def test_unknown_timer_value_counts_as_running():
    details = build_details(
        [sample(0, sumDuration=0.0), sample(3, sumDuration=None), sample(6, sumDuration=3.0)]
    )
    assert normalize_streams(details)["moving"].all()


def test_missing_channels_are_nan_and_cadence_fallback():
    details = build_details(
        [
            sample(0, directRunCadence=None, directBikeCadence=88.0),
            sample(1, directRunCadence=None, directBikeCadence=90.0),
        ]
    )
    df = normalize_streams(details)
    assert df["cadence"].tolist() == [88.0, 90.0]
    for col in ("hr", "speed", "alt", "lat", "lon", "distance"):
        assert df[col].isna().all(), col


def test_elapsed_duration_clock_when_no_timestamp():
    details = build_details(
        [
            {"sumElapsedDuration": 0.0, "directHeartRate": 90.0},
            {"sumElapsedDuration": 2.0, "directHeartRate": 95.0},
        ]
    )
    df = normalize_streams(details)
    assert df["t"].tolist() == [0, 1, 2]
    assert df["hr"].tolist() == [90.0, 90.0, 95.0]


def test_malformed_descriptors_and_short_rows_are_tolerated():
    details = {
        "metricDescriptors": [
            {"metricsIndex": 0, "key": "directTimestamp"},
            {"metricsIndex": 1, "key": "directHeartRate"},
            {"metricsIndex": -1, "key": "directSpeed"},
            {"metricsIndex": True, "key": "directElevation"},
            {"metricsIndex": 2, "key": None},
            "junk",
        ],
        "activityDetailMetrics": [
            {"metrics": [T0_MS, 100.0, 5.0]},
            {"metrics": [T0_MS + 1000]},
            {"metrics": [T0_MS + 2000, "x", 5.0]},
            {"nothing": True},
        ],
    }
    df = normalize_streams(details)
    assert df["t"].tolist() == [0, 1, 2]
    np.testing.assert_allclose(df["hr"], [100.0, np.nan, np.nan], equal_nan=True)
    assert df["speed"].isna().all() and df["alt"].isna().all()


@pytest.mark.parametrize(
    "details",
    [
        {},
        {"metricDescriptors": [{"metricsIndex": 0, "key": "directTimestamp"}], "activityDetailMetrics": []},
        {"metricDescriptors": None, "activityDetailMetrics": None},
        {"activityDetailMetrics": [{"metrics": [T0_MS, 100.0]}]},  # no descriptors
        build_details([{"directHeartRate": 100.0}]),  # no clock channel
        build_details([{"directTimestamp": None, "directHeartRate": 100.0}]),
    ],
    ids=["empty", "no-samples", "nulls", "no-descriptors", "no-clock", "null-clock"],
)
def test_empty_or_unusable_details_give_empty_frame(details):
    df = normalize_streams(details)
    assert df.empty
    assert list(df.columns) == STREAM_COLUMNS
    assert df["t"].dtype == np.int64 and df["moving"].dtype == bool


def test_single_sample():
    df = normalize_streams(build_details([sample(0, directHeartRate=100.0, sumDuration=0.0)]))
    assert df["t"].tolist() == [0]
    assert df["moving"].tolist() == [True]
    assert df["hr"].tolist() == [100.0]


def test_corrupt_timestamps_do_not_blow_up_the_grid():
    details = build_details(
        [
            {"directTimestamp": 0.0, "directHeartRate": 90.0},  # epoch 0 = no timestamp
            sample(0, directHeartRate=100.0),
            sample(1, directHeartRate=101.0),
            sample(10 * 24 * 3600, directHeartRate=102.0),  # 10 days later
        ]
    )
    df = normalize_streams(details)
    assert df["t"].tolist() == [0, 1]
    assert df["hr"].tolist() == [100.0, 101.0]
