"""PMC inputs and summaries (METRICS §4): daily load series and weekly aggregates.

Split from test_metrics_pmc.py (file size).

Every expected value is hand-computed; the derivation is in the comments (exact fractions where the
numbers are not round). Tolerance 1e-9 throughout.
"""

import math
from datetime import date

import numpy as np
import pandas as pd
import pytest

from tests.test_metrics_pmc import TEN_DAY_CTL
from training.metrics.pmc import (
    DAILY_LOAD_COLUMNS,
    WEEKLY_COLUMNS,
    daily_load_series,
    pmc,
    weekly_aggregates,
)

TOL = 1e-9
D0 = date(2026, 3, 2)  # a Monday; the first synced day of every synthetic series below


def load_series(loads: list[float], start: date = D0) -> pd.Series:
    index = pd.date_range(start, periods=len(loads), freq="D", name="date")
    return pd.Series(loads, index=index, dtype=float, name="load_total")


def assert_close(actual: pd.Series, expected: list[float | None]) -> None:
    """Element-wise |a − e| ≤ 1e-9; `None` means the value must be NaN."""
    assert len(actual) == len(expected)
    for i, (a, e) in enumerate(zip(actual.to_numpy(dtype=float), expected, strict=True)):
        if e is None:
            assert math.isnan(a), f"day {i}: expected NaN, got {a}"
        else:
            assert a == pytest.approx(e, abs=TOL), f"day {i}: expected {e}, got {a}"


# ---------------------------------------------------------------------------------------------------------
# daily_load_series
# ---------------------------------------------------------------------------------------------------------


def activities(rows: list[tuple]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["local_date", "sport", "load_primary"])


def test_daily_load_series_sums_splits_and_fills_rest_days() -> None:
    acts = activities(
        [
            (date(2026, 3, 1), "run", 999.0),  # before start → ignored
            (date(2026, 3, 2), "run", 50.0),
            (date(2026, 3, 2), "run", 25.0),  # second run on the same day
            (date(2026, 3, 2), "bike", 30.5),
            (date(2026, 3, 2), "other", 20.0),  # total only
            (date(2026, 3, 4), "run", None),  # null load → 0
            (date(2026, 3, 4), "bike", 40.0),
            (date(2026, 3, 5), "bike", float("nan")),  # null load → 0
            (date(2026, 3, 8), "run", 999.0),  # after end → ignored
        ]
    )
    out = daily_load_series(acts, date(2026, 3, 2), date(2026, 3, 7))
    assert isinstance(out.index, pd.DatetimeIndex)
    assert [d.date() for d in out.index] == [date(2026, 3, d) for d in range(2, 8)]
    assert list(out.columns) == list(DAILY_LOAD_COLUMNS)
    assert all(out[c].dtype == np.float64 for c in out.columns)
    # 03-02: total 50 + 25 + 30.5 + 20 = 125.5, run 75, bike 30.5; 03-04: total 40 (run null), bike 40.
    assert out["load_total"].tolist() == [125.5, 0.0, 40.0, 0.0, 0.0, 0.0]
    assert out["load_run"].tolist() == [75.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    assert out["load_bike"].tolist() == [30.5, 0.0, 40.0, 0.0, 0.0, 0.0]


def test_daily_load_series_empty_and_single_day() -> None:
    empty = daily_load_series(activities([]), date(2026, 3, 2), date(2026, 3, 4))
    assert len(empty) == 3
    assert (empty.to_numpy() == 0.0).all()
    one = daily_load_series(
        activities([(date(2026, 3, 2), "bike", 12.0)]), date(2026, 3, 2), date(2026, 3, 2)
    )
    assert one.to_dict("list") == {"load_total": [12.0], "load_run": [0.0], "load_bike": [12.0]}


def test_daily_load_series_feeds_pmc() -> None:
    acts = activities([(date(2026, 3, 2), "run", 100.0), (date(2026, 3, 4), "bike", 50.0)])
    daily = daily_load_series(acts, date(2026, 3, 2), date(2026, 3, 4))
    out = pmc(daily["load_total"])
    assert_close(out["ctl"], TEN_DAY_CTL[:3])  # loads 100, 0, 50 = start of the 10-day series
    assert out.index.equals(daily.index)


# ---------------------------------------------------------------------------------------------------------
# weekly_aggregates
# ---------------------------------------------------------------------------------------------------------


def tiz(z1: int, z2: int, z3: int, z4: int, z5: int) -> dict[str, int]:
    return {"1": z1, "2": z2, "3": z3, "4": z4, "5": z5}


WEEK_ROWS = [
    # 2025-12-28 is a Sunday → ISO 2025-W52 (Monday 2025-12-22)
    (date(2025, 12, 28), "run", 60.0, 3600.0, 12000.0, 100.0, tiz(600, 2400, 300, 200, 100)),
    # 2025-12-29 is a Monday → ISO 2026-W01, which runs to Sunday 2026-01-04
    (date(2025, 12, 29), "run", 50.0, 3000.0, 10000.0, 50.0, tiz(1000, 1000, 500, 300, 200)),
    (date(2026, 1, 1), "bike", 80.0, 7200.0, 60000.0, 500.0, tiz(3600, 2400, 1200, 0, 0)),
    (date(2026, 1, 4), "run", None, 1800.0, 5000.0, None, None),
    (date(2026, 1, 4), "other", 20.0, 1200.0, None, None, tiz(0, 0, 0, 0, 0)),
    # 2026-01-05 is a Monday → ISO 2026-W02
    (date(2026, 1, 5), "other", 10.0, 900.0, None, None, None),
]
WEEK_COLUMNS_IN = [
    "local_date",
    "sport",
    "load_primary",
    "duration_s",
    "distance_m",
    "elev_gain_m",
    "time_in_hr_zone",
]

# Per row: (week_start, iso_year, iso_week, sport), (n, load, duration_s, distance_m, elev_gain_m),
# (tiz_1..tiz_5), (pol_low, pol_mid, pol_high) with pol = (Z1+Z2, Z3, Z4+Z5) / Σ zones, None if Σ is 0.
W52, W01, W02 = date(2025, 12, 22), date(2025, 12, 29), date(2026, 1, 5)
NO_ZONES = (0, 0, 0, 0, 0)
NO_SHARES = (None, None, None)
EXPECTED_WEEKS = [
    # W52: 3000/3600, 300/3600, 300/3600
    (
        (W52, 2025, 52, "run"),
        (1, 60.0, 3600.0, 12000.0, 100.0),
        (600, 2400, 300, 200, 100),
        (5 / 6, 1 / 12, 1 / 12),
    ),
    (
        (W52, 2025, 52, "all"),
        (1, 60.0, 3600.0, 12000.0, 100.0),
        (600, 2400, 300, 200, 100),
        (5 / 6, 1 / 12, 1 / 12),
    ),
    # W01 run: 2 runs, one with null load / elevation / zones → 2000/3000, 500/3000, 500/3000
    (
        (W01, 2026, 1, "run"),
        (2, 50.0, 4800.0, 15000.0, 50.0),
        (1000, 1000, 500, 300, 200),
        (2 / 3, 1 / 6, 1 / 6),
    ),
    # W01 bike: 6000/7200, 1200/7200, 0
    (
        (W01, 2026, 1, "bike"),
        (1, 80.0, 7200.0, 60000.0, 500.0),
        (3600, 2400, 1200, 0, 0),
        (5 / 6, 1 / 6, 0.0),
    ),
    # W01 other: all zones 0 → no polarization; null distance / elevation → 0
    ((W01, 2026, 1, "other"), (1, 20.0, 1200.0, 0.0, 0.0), NO_ZONES, NO_SHARES),
    # W01 all: zones 4600, 3400, 1700, 300, 200 (Σ 10200) → 8000/10200, 1700/10200, 500/10200
    (
        (W01, 2026, 1, "all"),
        (4, 150.0, 13200.0, 75000.0, 550.0),
        (4600, 3400, 1700, 300, 200),
        (40 / 51, 1 / 6, 5 / 102),
    ),
    # W02: one "other" without zones
    ((W02, 2026, 2, "other"), (1, 10.0, 900.0, 0.0, 0.0), NO_ZONES, NO_SHARES),
    ((W02, 2026, 2, "all"), (1, 10.0, 900.0, 0.0, 0.0), NO_ZONES, NO_SHARES),
]


def test_weekly_aggregates_iso_weeks_sports_and_polarization() -> None:
    out = weekly_aggregates(pd.DataFrame(WEEK_ROWS, columns=WEEK_COLUMNS_IN))
    assert list(out.columns) == list(WEEKLY_COLUMNS)
    assert len(out) == len(EXPECTED_WEEKS)
    for (_, row), (key, totals, zones, shares) in zip(out.iterrows(), EXPECTED_WEEKS, strict=True):
        week_start, iso_year, iso_week, sport = key
        n, load, duration, distance, elev = totals
        assert row["week_start"] == week_start and type(row["week_start"]) is date
        assert (row["iso_year"], row["iso_week"], row["sport"]) == (iso_year, iso_week, sport)
        assert row["n_activities"] == n
        assert row["load"] == pytest.approx(load, abs=TOL)
        assert row["duration_s"] == pytest.approx(duration, abs=TOL)
        assert row["distance_m"] == pytest.approx(distance, abs=TOL)
        assert row["elev_gain_m"] == pytest.approx(elev, abs=TOL)
        assert [row[f"tiz_{z}"] for z in range(1, 6)] == pytest.approx(list(zones), abs=TOL)
        for name, share in zip(("pol_low", "pol_mid", "pol_high"), shares, strict=True):
            if share is None:
                assert row[name] is None, f"{name} {week_start} {sport}"
            else:
                assert row[name] == pytest.approx(share, abs=TOL), f"{name} {week_start} {sport}"


def test_weekly_aggregates_shares_sum_to_one() -> None:
    out = weekly_aggregates(pd.DataFrame(WEEK_ROWS, columns=WEEK_COLUMNS_IN))
    with_zones = out[out["pol_low"].notna()]
    total = with_zones["pol_low"] + with_zones["pol_mid"] + with_zones["pol_high"]
    assert total.to_numpy(dtype=float) == pytest.approx([1.0] * len(with_zones), abs=TOL)


@pytest.mark.parametrize(
    ("day", "week_start", "iso_year", "iso_week"),
    [
        (date(2025, 12, 29), date(2025, 12, 29), 2026, 1),  # Monday belongs to next ISO year
        (date(2026, 1, 4), date(2025, 12, 29), 2026, 1),  # Sunday closes the week
        (date(2024, 12, 31), date(2024, 12, 30), 2025, 1),
        (date(2021, 1, 3), date(2020, 12, 28), 2020, 53),  # Sunday in January still in week 53
        (date(2026, 3, 2), date(2026, 3, 2), 2026, 10),
    ],
)
def test_weekly_aggregates_iso_week_of_date(
    day: date, week_start: date, iso_year: int, iso_week: int
) -> None:
    row = (day, "run", 10.0, 600.0, 2000.0, 5.0, None)
    out = weekly_aggregates(pd.DataFrame([row], columns=WEEK_COLUMNS_IN))
    assert out["sport"].tolist() == ["run", "all"]
    assert out["week_start"].tolist() == [week_start, week_start]
    assert out["iso_year"].tolist() == [iso_year, iso_year]
    assert out["iso_week"].tolist() == [iso_week, iso_week]


def test_weekly_aggregates_empty() -> None:
    out = weekly_aggregates(pd.DataFrame([], columns=WEEK_COLUMNS_IN))
    assert out.empty
    assert list(out.columns) == list(WEEKLY_COLUMNS)
