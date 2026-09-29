"""EF trend – METRICS §5.2 (28-day rolling median over steady-state runs).

# METRICS §5.2
Trend: 28-day rolling median over steady-state runs. (Clarified: trend on day d = median EF of the
steady-state runs with `local_date` in [d − 27, d]; null if none.)
(Steady state, EF, decoupling: test_metrics_efficiency.py.)
"""

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from training.metrics.efficiency import ef_trend

# ---------------------------------------------------------------- §5.2 trend


def _points(rows: list[tuple[date, float | None, bool]]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["local_date", "ef", "steady_state"])


def test_ef_trend_window_edges():
    d = date(2026, 9, 29)
    points = _points(
        [
            (d - timedelta(days=28), 9.0, True),  # out
            (d - timedelta(days=27), 1.0, True),  # in
            (d, 2.0, True),  # in
            (d + timedelta(days=1), 9.0, True),  # future → out
        ]
    )
    out = ef_trend(points, [d])
    assert out.index.tolist() == [d]
    assert out[d] == pytest.approx(1.5)


def test_ef_trend_ignores_non_steady_and_null_and_gives_nan():
    d = date(2026, 9, 29)
    points = _points([(d, 5.0, False), (d, None, True), (d - timedelta(days=1), 1.3, True)])
    out = ef_trend(points, [d - timedelta(days=2), d - timedelta(days=1), d])
    assert np.isnan(out.iloc[0])
    assert out.iloc[1] == pytest.approx(1.3)
    assert out.iloc[2] == pytest.approx(1.3)


def test_ef_trend_median_odd_and_timestamps():
    d = date(2026, 3, 1)
    points = _points([(d, 1.0, True), (d, 3.0, True), (d - timedelta(days=5), 1.1, True)])
    points["local_date"] = pd.to_datetime(points["local_date"])  # datetime64 input works too
    assert ef_trend(points, [d])[d] == pytest.approx(1.1)


def test_ef_trend_empty():
    out = ef_trend(_points([]), [date(2026, 1, 1)])
    assert len(out) == 1 and np.isnan(out.iloc[0])
    assert ef_trend(_points([]), []).empty
