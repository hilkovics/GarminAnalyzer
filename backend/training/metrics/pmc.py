"""Performance Management Chart: daily load, CTL/ATL/TSB, ACWR, monotony, weekly aggregates – METRICS §4.

Pure functions over pandas/numpy; no I/O.

# METRICS §4
#   daily_load[d] = Σ load_primary of activities whose local start date is d (0 on rest days).
#   Series starts at the first synced day.
#   CTL[d] = CTL[d−1] + (daily_load[d] − CTL[d−1]) / 42
#   ATL[d] = ATL[d−1] + (daily_load[d] − ATL[d−1]) / 7
#   TSB[d] = CTL[d−1] − ATL[d−1]
#   acute = mean(daily_load[d−6..d]), chronic = mean(daily_load[d−27..d]), ACWR = acute / chronic
#     (NaN if chronic < 5). Bands: < 0.8 under, 0.8–1.3 optimal, 1.3–1.5 caution, > 1.5 danger.
#   monotony = mean7 / std7 of daily loads (NaN if std7 == 0 or fewer than 4 training days in 28 d).
#   strain = sum7 · monotony
#   ramp_rate = CTL[d] − CTL[d−7]. Warn if > 6.
#   Weekly aggregates: ISO weeks, per sport: load, duration, distance, elevation, time_in_zone.
#     Polarization index = share of time in Z1–Z2 vs Z3 vs Z4–Z5.
# Clarified 2026-09-29 (phase 2, proposed):
#   CTL / ATL of the day before the first day are 0, so the first day's TSB is 0.
#   Windows (acute, chronic, mean7, std7, sum7, the 28-day training-day count) include day d and need their
#   full length of series history; before that the value is NaN. std7 is the population standard deviation
#   (ddof = 0). A training day is a day with daily_load > 0.
#   ramp_rate is NaN for the first 7 days. ramp_warning = ramp_rate > 6, acwr_band per the bands above
#   (NaN → no band).
#   daily_load is split into load_run, load_bike (and other, part of the total only). An activity with a
#   null load_primary contributes 0.
#   Weekly aggregates: ISO week (Monday start). Duration = duration_s (timer time). Polarization shares use
#   the HR time_in_zone totals of the week: (Z1+Z2, Z3, Z4+Z5) / total, null if the total is 0.

Band edges: the spec's ranges touch at 0.8, 1.3 and 1.5; they are read as half-open
`[0.8, 1.3)` optimal, `[1.3, 1.5]` caution, `> 1.5` danger (and `< 0.8` under).
"""

from collections.abc import Callable
from datetime import date
from typing import Any

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

# METRICS §4 constants (do not change without changing METRICS.md first).
CTL_DAYS = 42
ATL_DAYS = 7
ACUTE_WINDOW_D = 7
CHRONIC_WINDOW_D = 28
ACWR_MIN_CHRONIC = 5.0
ACWR_OPTIMAL_FROM = 0.8  # acwr < 0.8 → under
ACWR_CAUTION_FROM = 1.3  # 0.8 ≤ acwr < 1.3 → optimal
ACWR_DANGER_ABOVE = 1.5  # 1.3 ≤ acwr ≤ 1.5 → caution, above → danger
MONOTONY_WINDOW_D = 7
TRAINING_DAY_WINDOW_D = 28
MONOTONY_MIN_TRAINING_DAYS = 4
RAMP_LAG_D = 7
RAMP_WARNING_ABOVE = 6.0

SPORTS_SPLIT = ("run", "bike")  # `other` (and anything unknown) counts in load_total only
DAILY_LOAD_COLUMNS = ("load_total", "load_run", "load_bike")
PMC_COLUMNS = (
    "ctl",
    "atl",
    "tsb",
    "acwr",
    "acwr_band",
    "monotony",
    "strain",
    "ramp_rate",
    "ramp_warning",
)
HR_ZONES = ("1", "2", "3", "4", "5")
WEEKLY_COLUMNS = (
    "week_start",
    "iso_year",
    "iso_week",
    "sport",
    "n_activities",
    "load",
    "duration_s",
    "distance_m",
    "elev_gain_m",
    *(f"tiz_{z}" for z in HR_ZONES),
    "pol_low",
    "pol_mid",
    "pol_high",
)
ALL_SPORTS = "all"
_SPORT_ORDER = {"run": 0, "bike": 1, "other": 2}  # then unknown sports alphabetically, then "all"


def daily_load_series(activities: pd.DataFrame, start: date, end: date) -> pd.DataFrame:
    """Daily load per calendar day `start..end` (inclusive) – METRICS §4.

    `activities` needs `local_date` (date), `sport` and `load_primary`. Activities outside [start, end] are
    ignored; a null `load_primary` contributes 0; `other` (or any sport other than run/bike) counts in
    `load_total` only.

    Returns a DataFrame indexed by a daily `DatetimeIndex` named `date` (midnight timestamps; use
    `.date()` for `datetime.date`), columns `load_total`, `load_run`, `load_bike` (float, 0 on rest days).
    `end < start` gives an empty frame.
    """
    first, last = pd.Timestamp(start).normalize(), pd.Timestamp(end).normalize()
    index = pd.date_range(first, last, freq="D", name="date")
    totals = {column: np.zeros(len(index)) for column in DAILY_LOAD_COLUMNS}
    if len(activities) and len(index):
        days = pd.to_datetime(pd.Series(activities["local_date"].to_numpy())).dt.normalize()
        offset = ((days - first) // pd.Timedelta(days=1)).to_numpy(dtype=float, na_value=np.nan)
        load = _numeric(activities["load_primary"])
        sport = activities["sport"].to_numpy(dtype=object)
        inside = (offset >= 0) & (offset < len(index))  # NaN (no date) compares False
        for column, mask in (
            ("load_total", inside),
            *((f"load_{name}", inside & (sport == name)) for name in SPORTS_SPLIT),
        ):
            np.add.at(totals[column], offset[mask].astype(int), load[mask])
    return pd.DataFrame(totals, index=index)


def acwr_band(acwr: float | None) -> str | None:
    """ACWR band – METRICS §4: < 0.8 under, [0.8, 1.3) optimal, [1.3, 1.5] caution, > 1.5 danger.

    NaN / None → None (no band).
    """
    if acwr is None or np.isnan(acwr):
        return None
    if acwr < ACWR_OPTIMAL_FROM:
        return "under"
    if acwr < ACWR_CAUTION_FROM:
        return "optimal"
    if acwr <= ACWR_DANGER_ABOVE:
        return "caution"
    return "danger"


def pmc(daily_load: pd.Series) -> pd.DataFrame:
    """CTL, ATL, TSB, ACWR (+ band), monotony, strain, ramp rate (+ warning) per day – METRICS §4.

    `daily_load` is `load_total` with one value per consecutive calendar day (DatetimeIndex or
    `datetime.date` index), starting at the first synced day: CTL and ATL of the day before the first
    entry are 0, so the whole series must always be passed (a shorter tail gives different values).
    The output keeps the input index. NaN loads or missing days raise `ValueError`.

    Window metrics need their full length of history and are NaN before that: ACWR and monotony/strain
    from the 28th day (the chronic window and the 28-day training-day count), ramp_rate from the 8th day.
    `acwr_band` is a str or None (object column), `ramp_warning` a bool (False where ramp_rate is NaN).
    """
    _check_consecutive_days(daily_load.index)
    load = daily_load.to_numpy(dtype=float)
    if np.isnan(load).any():
        raise ValueError("pmc() got NaN daily loads; rest days must be 0")
    n = len(load)

    ctl, atl, tsb = np.empty(n), np.empty(n), np.empty(n)
    ctl_prev = atl_prev = 0.0  # CTL[−1] = ATL[−1] = 0
    for d, x in enumerate(load):
        tsb[d] = ctl_prev - atl_prev
        ctl_prev = ctl_prev + (x - ctl_prev) / CTL_DAYS
        atl_prev = atl_prev + (x - atl_prev) / ATL_DAYS
        ctl[d], atl[d] = ctl_prev, atl_prev

    acute = _trailing(load, ACUTE_WINDOW_D, np.mean)
    chronic = _trailing(load, CHRONIC_WINDOW_D, np.mean)
    with np.errstate(divide="ignore", invalid="ignore"):
        acwr = np.where(chronic >= ACWR_MIN_CHRONIC, acute / chronic, np.nan)

    mean7 = _trailing(load, MONOTONY_WINDOW_D, np.mean)
    sum7 = _trailing(load, MONOTONY_WINDOW_D, np.sum)
    std7 = _trailing(load, MONOTONY_WINDOW_D, lambda w, axis: np.std(w, axis=axis, ddof=0))
    # std7 == 0 exactly when the window is constant; test that directly so float residue of a
    # constant window (e.g. seven 0.1 loads) cannot turn into a huge monotony.
    spread7 = _trailing(load, MONOTONY_WINDOW_D, np.max) - _trailing(load, MONOTONY_WINDOW_D, np.min)
    std7 = np.where(spread7 == 0, 0.0, std7)
    training_days = _trailing((load > 0).astype(float), TRAINING_DAY_WINDOW_D, np.sum)
    valid = (std7 > 0) & (training_days >= MONOTONY_MIN_TRAINING_DAYS)
    with np.errstate(divide="ignore", invalid="ignore"):
        monotony = np.where(valid, mean7 / std7, np.nan)
    strain = sum7 * monotony

    ramp = np.full(n, np.nan)
    if n > RAMP_LAG_D:
        ramp[RAMP_LAG_D:] = ctl[RAMP_LAG_D:] - ctl[:-RAMP_LAG_D]
    ramp_warning = ramp > RAMP_WARNING_ABOVE  # NaN compares False

    return pd.DataFrame(
        {
            "ctl": ctl,
            "atl": atl,
            "tsb": tsb,
            "acwr": acwr,
            "acwr_band": pd.Series([acwr_band(v) for v in acwr], index=daily_load.index, dtype=object),
            "monotony": monotony,
            "strain": strain,
            "ramp_rate": ramp,
            "ramp_warning": ramp_warning,
        },
        index=daily_load.index,
    )


def weekly_aggregates(activities: pd.DataFrame) -> pd.DataFrame:
    """Per ISO week (Monday start) and sport, plus a `sport == "all"` row per week – METRICS §4.

    `activities` needs `local_date`, `sport`, `load_primary`, `duration_s`, `distance_m`, `elev_gain_m`
    and `time_in_hr_zone` (`{"1": s, …, "5": s}` or None). Null numbers count as 0; activities without
    zones add nothing to `tiz_*`.

    Returns one row per (week, sport) that has activities, followed by the week's "all" row (weeks without
    activities are absent), ordered by week, then run, bike, other, other sports alphabetically, all.
    Columns: `week_start` (date), `iso_year`, `iso_week`, `sport`, `n_activities`, `load`, `duration_s`,
    `distance_m`, `elev_gain_m`, `tiz_1..tiz_5` (seconds, float), `pol_low`, `pol_mid`, `pol_high`
    (shares `(Z1+Z2, Z3, Z4+Z5) / Σ zones`, None when the week's zone total is 0).
    """
    if len(activities) == 0:
        return pd.DataFrame({column: pd.Series(dtype=object) for column in WEEKLY_COLUMNS})

    days = pd.to_datetime(pd.Series(activities["local_date"].to_numpy())).dt.normalize()
    iso = days.dt.isocalendar()
    week_start = days - pd.to_timedelta(iso["day"].astype(int) - 1, unit="D")
    frame = pd.DataFrame(
        {
            "week_start": [ts.date() for ts in week_start],
            "iso_year": iso["year"].astype(int).to_numpy(),
            "iso_week": iso["week"].astype(int).to_numpy(),
            "sport": activities["sport"].to_numpy(dtype=object),
            "load": _numeric(activities["load_primary"]),
            "duration_s": _numeric(activities["duration_s"]),
            "distance_m": _numeric(activities["distance_m"]),
            "elev_gain_m": _numeric(activities["elev_gain_m"]),
        }
    )
    zones = [_zone_seconds(v) for v in activities["time_in_hr_zone"]]
    for i, z in enumerate(HR_ZONES):
        frame[f"tiz_{z}"] = [row[i] for row in zones]

    week_keys = ["week_start", "iso_year", "iso_week"]
    sums = {c: "sum" for c in ("load", "duration_s", "distance_m", "elev_gain_m", *_tiz_columns())}
    per_sport = frame.groupby([*week_keys, "sport"], sort=False).agg(
        n_activities=("load", "size"), **_named(sums)
    )
    per_week = frame.groupby(week_keys, sort=False).agg(n_activities=("load", "size"), **_named(sums))
    per_week["sport"] = ALL_SPORTS
    out = pd.concat([per_sport.reset_index(), per_week.reset_index()], ignore_index=True)

    shares = [_polarization(row) for row in out[list(_tiz_columns())].to_numpy(dtype=float)]
    for i, column in enumerate(("pol_low", "pol_mid", "pol_high")):
        out[column] = pd.Series([s[i] for s in shares], dtype=object)

    out["_rank"] = [4 if s == ALL_SPORTS else _SPORT_ORDER.get(s, 3) for s in out["sport"]]
    out = out.sort_values(["week_start", "_rank", "sport"], kind="stable").drop(columns="_rank")
    out["n_activities"] = out["n_activities"].astype(int)
    return out[list(WEEKLY_COLUMNS)].reset_index(drop=True)


def _check_consecutive_days(index: pd.Index) -> None:
    if len(index) < 2:
        return
    days = pd.DatetimeIndex(pd.to_datetime(index)).to_numpy()
    if not (np.diff(days) == np.timedelta64(1, "D")).all():
        raise ValueError("pmc() needs one value per consecutive calendar day (fill rest days with 0)")


def _trailing(values: np.ndarray, window: int, reduce: Callable[..., np.ndarray]) -> np.ndarray:
    """Trailing window over values[d−window+1..d]; NaN until the full window is available."""
    out = np.full(len(values), np.nan)
    if len(values) >= window:
        out[window - 1 :] = reduce(sliding_window_view(values, window), axis=1)
    return out


def _numeric(column: pd.Series) -> np.ndarray:
    return pd.to_numeric(pd.Series(column.to_numpy()), errors="coerce").fillna(0.0).to_numpy(dtype=float)


def _zone_seconds(time_in_zone: Any) -> tuple[float, ...]:
    if not isinstance(time_in_zone, dict):
        return (0.0,) * len(HR_ZONES)
    return tuple(float(time_in_zone.get(z) or 0.0) for z in HR_ZONES)


def _tiz_columns() -> tuple[str, ...]:
    return tuple(f"tiz_{z}" for z in HR_ZONES)


def _named(sums: dict[str, str]) -> dict[str, tuple[str, str]]:
    return {column: (column, how) for column, how in sums.items()}


def _polarization(tiz: np.ndarray) -> tuple[float | None, float | None, float | None]:
    """(Z1+Z2, Z3, Z4+Z5) / total – METRICS §4; None if the total is 0."""
    total = float(tiz.sum())
    if total == 0:
        return (None, None, None)
    return (float(tiz[0] + tiz[1]) / total, float(tiz[2]) / total, float(tiz[3] + tiz[4]) / total)
