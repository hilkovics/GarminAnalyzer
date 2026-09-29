"""Trailing best-per-window curves over stored best efforts – METRICS §6.2.

# METRICS §6.2
Curves: best per W over trailing 90 days and all-time.
Clarified 2026-09-29 (phase 4, proposed): trailing 90 days = `local_date` in [today − 89, today].
(Per-activity best efforts: test_metrics_efforts.py.)
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from training.metrics.efforts import best_per_window

TODAY = date(2026, 9, 29)


# ---------------------------------------------------------------- best_per_window


def efforts_frame(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["local_date", "kind", "window_s", "value", "activity_id"])


def test_best_per_window_90_day_edges():
    df = efforts_frame(
        [
            (TODAY - timedelta(days=89), "gap_speed", 300, 5.0, 1),  # in (edge)
            (TODAY - timedelta(days=90), "gap_speed", 300, 6.0, 2),  # out (edge)
            (TODAY - timedelta(days=10), "gap_speed", 300, 4.0, 3),
            (TODAY, "gap_speed", 600, 3.9, 4),  # today is in
            (TODAY - timedelta(days=5), "hr", 1200, 171.0, 3),
        ]
    )
    out = best_per_window(df, today=TODAY)
    assert list(out.columns) == ["kind", "window_s", "value", "local_date", "activity_id"]
    rows = {(r.kind, r.window_s): r for r in out.itertuples()}
    assert set(rows) == {("gap_speed", 300), ("gap_speed", 600), ("hr", 1200)}
    assert rows[("gap_speed", 300)].value == 5.0
    assert rows[("gap_speed", 300)].local_date == TODAY - timedelta(days=89)
    assert rows[("gap_speed", 300)].activity_id == 1
    assert rows[("gap_speed", 600)].local_date == TODAY
    assert rows[("hr", 1200)].value == 171.0


def test_best_per_window_all_time():
    df = efforts_frame(
        [
            (TODAY - timedelta(days=89), "gap_speed", 300, 5.0, 1),
            (TODAY - timedelta(days=900), "gap_speed", 300, 6.0, 2),
        ]
    )
    out = best_per_window(df, today=TODAY, days=None)
    assert len(out) == 1
    row = out.iloc[0]
    assert row["value"] == 6.0
    assert row["local_date"] == TODAY - timedelta(days=900)
    assert row["activity_id"] == 2


def test_best_per_window_custom_days():
    df = efforts_frame(
        [
            (TODAY - timedelta(days=27), "gap_speed", 60, 5.0, 1),
            (TODAY - timedelta(days=28), "gap_speed", 60, 6.0, 2),
        ]
    )
    assert best_per_window(df, today=TODAY, days=28).iloc[0]["value"] == 5.0


def test_best_per_window_excludes_future_dates():
    df = efforts_frame(
        [
            (TODAY + timedelta(days=1), "gap_speed", 60, 9.0, 1),
            (TODAY, "gap_speed", 60, 5.0, 2),
        ]
    )
    assert best_per_window(df, today=TODAY).iloc[0]["value"] == 5.0
    assert best_per_window(df, today=TODAY, days=None).iloc[0]["value"] == 5.0


def test_best_per_window_tie_takes_earliest():
    df = efforts_frame(
        [
            (TODAY - timedelta(days=3), "gap_speed", 60, 5.0, 7),
            (TODAY - timedelta(days=30), "gap_speed", 60, 5.0, 8),
        ]
    )
    row = best_per_window(df, today=TODAY).iloc[0]
    assert row["local_date"] == TODAY - timedelta(days=30)
    assert row["activity_id"] == 8


def test_best_per_window_without_activity_id_and_timestamp_dates():
    df = pd.DataFrame(
        {
            "local_date": pd.to_datetime(["2026-09-01", "2026-09-02"]),
            "kind": ["speed", "speed"],
            "window_s": [300, 300],
            "value": [9.0, 10.0],
        }
    )
    out = best_per_window(df, today=TODAY)
    assert len(out) == 1
    assert out.iloc[0]["value"] == 10.0
    assert out.iloc[0]["local_date"] == date(2026, 9, 2)
    assert out.iloc[0]["activity_id"] is None


def test_best_per_window_empty():
    out = best_per_window(efforts_frame([]), today=TODAY)
    assert out.empty
    assert list(out.columns) == ["kind", "window_s", "value", "local_date", "activity_id"]
    out = best_per_window(efforts_frame([(TODAY - timedelta(days=200), "hr", 1200, 170.0, 1)]), today=TODAY)
    assert out.empty


def test_best_per_window_ignores_nan_values():
    df = efforts_frame(
        [
            (TODAY, "gap_speed", 60, np.nan, 1),
            (TODAY - timedelta(days=1), "gap_speed", 60, 4.0, 2),
        ]
    )
    assert best_per_window(df, today=TODAY).iloc[0]["value"] == 4.0
