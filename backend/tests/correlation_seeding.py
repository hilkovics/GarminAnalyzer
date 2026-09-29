"""Synthetic builders for the METRICS §9 correlation tests."""

from datetime import date, timedelta

import numpy as np
import pandas as pd

from training.analysis.correlation import (
    BASE_PREDICTORS,
    CONTROLS,
    OUTCOMES,
    CorrelationResult,
    correlate,
    predictor_columns,
)

TOL = 1e-9
D0 = date(2026, 3, 2)
H = 3600.0

ACTIVITY_COLUMNS = [
    "activity_id",
    "local_date",
    "sport",
    "moving_s",
    "load_method",
    "if_hr",
    "if_pace",
    "ef",
    "decoupling_pct",
    "pace_at_ref_hr_day",
    "rpe",
]


# --------------------------------------------------------------------------------------------------
# synthetic inputs


def day(i: int) -> date:
    return D0 + timedelta(days=i)


def ts(i: int) -> pd.Timestamp:
    return pd.Timestamp(day(i))


def activity(
    activity_id: int,
    i: int,
    *,
    sport: str = "run",
    moving_s: float = H,
    load_method: str | None = "rtss",
    if_hr: float = 0.8,
    if_pace: float = 0.85,
    ef: float | None = 1.5,
    decoupling_pct: float | None = 3.0,
    pace_at_ref_hr_day: float | None = 3.2,
    rpe: float | None = None,
) -> dict:
    return {
        "activity_id": activity_id,
        "local_date": day(i),
        "sport": sport,
        "moving_s": moving_s,
        "load_method": load_method,
        "if_hr": if_hr,
        "if_pace": if_pace,
        "ef": ef,
        "decoupling_pct": decoupling_pct,
        "pace_at_ref_hr_day": pace_at_ref_hr_day,
        "rpe": rpe,
    }


def activities_frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=ACTIVITY_COLUMNS)


def wellness_frame(rows: dict[int, dict[str, float]]) -> pd.DataFrame:
    """Sparse wellness: only the given day offsets exist, indexed by `datetime.date`."""
    columns = [*BASE_PREDICTORS, "sleep_debt_7"]
    index = pd.Index([day(i) for i in sorted(rows)], name="date")
    data = [[rows[i].get(c, np.nan) for c in columns] for i in sorted(rows)]
    return pd.DataFrame(data, index=index, columns=columns, dtype=float)


def daily_frame(first: int = 0, last: int = 20) -> pd.DataFrame:
    """Full daily series; tsb = 100 + i, atl = 200 + i, load_total = 300 + i (day offset i)."""
    offsets = np.arange(first, last + 1)
    index = pd.date_range(ts(first), ts(last), freq="D", name="date")
    return pd.DataFrame(
        {"load_total": 300.0 + offsets, "atl": 200.0 + offsets, "tsb": 100.0 + offsets}, index=index
    )


def full_dataset(n: int, seed: int = 1, *, sport: str = "run") -> pd.DataFrame:
    """A dataset shaped like `build_dataset` output with every column filled (random, independent)."""
    rng = np.random.default_rng(seed)
    index = pd.date_range(ts(0), periods=n, freq="D", name="date")
    data: dict[str, np.ndarray] = {"activity_id": np.arange(n)}
    for column in (*OUTCOMES, *predictor_columns(), *CONTROLS):
        data[column] = rng.normal(size=n)
    if sport == "bike":
        data["pace_at_ref_hr_day"] = np.full(n, np.nan)
    return pd.DataFrame(data, index=index)


def controls_frame(rng: np.random.Generator, n: int, tsb: np.ndarray | None = None) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "tsb": rng.normal(0, 10, n) if tsb is None else tsb,
            "atl_prev": rng.normal(60, 15, n),
            "load_prev": rng.normal(80, 30, n),
        }
    )


def run_correlate(x, y, controls, **kwargs) -> CorrelationResult:
    return correlate(x, y, controls, sport="run", predictor="sleep_s_lag0", outcome="ef", **kwargs)
