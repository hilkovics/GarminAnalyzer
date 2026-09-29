"""Wellness baselines (28-day median / MAD) and 7-night sleep debt – METRICS §8, §9 (phase 5).

Pure functions over pandas/numpy; no I/O.

# METRICS §8
#   Baselines: trailing 28-day median and MAD (median absolute deviation) for
#   rhr, sleep_s, sleep_score, body_battery_wake.
# Clarified 2026-09-29 (phase 5, proposed):
#   Wellness row D = the night that ends on the morning of D (Garmin's sleep calendarDate), RHR / Body
#   Battery of day D.
#   Baseline of day D = median and MAD over the valid values of the 28 days D−28 … D−1 (day D itself is
#   excluded, so a bad night cannot pull its own baseline). Needs ≥ 7 valid values, else null. MAD is the
#   raw median absolute deviation (no 1.4826 scaling); it is only displayed (baseline ± MAD band).
#
# METRICS §9
#   sleep_debt_7 = Σ_{7 nights} (max(8 h, sleep_s_median28) − sleep_s)
# Clarified 2026-09-29 (phase 5, proposed):
#   sleep_debt_7 is lag0 only: the sum over nights D−6 … D, each term using that night's §8 baseline
#   (7.5 h floor replaced by 8 h here, as written). Surpluses offset deficits. It needs ≥ 5 valid nights,
#   and the sum is scaled by 7 / n_valid.

Windows are calendar days: a sparse date index is reindexed to the full daily range internally, so a
missing day is simply a missing value. A null nightly baseline in the sleep debt uses the 8 h floor.
"""

import warnings
from datetime import date

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

# METRICS §8 / §9 constants (do not change without changing METRICS.md first).
BASELINE_FIELDS = ("rhr", "sleep_s", "sleep_score", "body_battery_wake")
BASELINE_DAYS = 28
MIN_BASELINE_VALUES = 7
SLEEP_DEBT_NIGHTS = 7
SLEEP_DEBT_MIN_NIGHTS = 5
SLEEP_DEBT_FLOOR_S = 8 * 3600.0


def baseline_columns() -> tuple[str, ...]:
    """Column names produced by `baselines`, in output order."""
    return tuple(f"{f}_{stat}" for f in BASELINE_FIELDS for stat in ("median28", "mad28"))


def baselines(wellness: pd.DataFrame) -> pd.DataFrame:
    """Trailing 28-day median / raw MAD of each baseline field (METRICS §8, phase 5 clarification).

    `wellness` is indexed by `datetime.date` (days may be missing) and has any subset of
    `BASELINE_FIELDS`; absent columns count as all-NaN. The baseline of day D uses the valid values of
    calendar days D−28 … D−1 and is NaN with fewer than 7 of them. The output keeps the input index and
    has the columns `f"{f}_median28"`, `f"{f}_mad28"` for every field. Duplicate dates raise `ValueError`.
    """
    days = _date_index(wellness.index)
    out = pd.DataFrame(index=wellness.index, columns=list(baseline_columns()), dtype=float)
    if len(days) == 0:
        return out
    full = _full_range(days)
    positions = _positions(full, days)
    for field in BASELINE_FIELDS:
        values = np.full(len(full), np.nan)
        if field in wellness.columns:
            values[positions] = _numeric(wellness[field])
        median, mad = _trailing_median_mad(values)
        out[f"{field}_median28"] = median[positions]
        out[f"{field}_mad28"] = mad[positions]
    return out


def sleep_debt_7(sleep_s: pd.Series, sleep_s_median28: pd.Series) -> pd.Series:
    """7-night sleep debt in seconds (METRICS §9, phase 5 clarification).

    Per night: `max(8 h, sleep_s_median28) − sleep_s` (8 h when the median is null; surpluses are
    negative and offset deficits). Day D sums the valid nights of calendar nights D−6 … D, needs ≥ 5 of
    them (else NaN) and is scaled by `7 / n_valid`. Both inputs are date-indexed; the median is aligned
    by date. The output is indexed like `sleep_s`.
    """
    days = _date_index(sleep_s.index)
    if len(days) == 0:
        return pd.Series(np.nan, index=sleep_s.index, dtype=float, name="sleep_debt_7")
    full = _full_range(days)
    positions = _positions(full, days)
    sleep = np.full(len(full), np.nan)
    sleep[positions] = _numeric(sleep_s)
    median = _align(sleep_s_median28, full)
    floor = np.where(np.isnan(median), SLEEP_DEBT_FLOOR_S, np.maximum(SLEEP_DEBT_FLOOR_S, median))
    terms = floor - sleep  # NaN where the night is missing

    padded = np.concatenate([np.full(SLEEP_DEBT_NIGHTS - 1, np.nan), terms])
    windows = sliding_window_view(padded, SLEEP_DEBT_NIGHTS)  # row i = nights i−6 … i
    n_valid = np.sum(~np.isnan(windows), axis=1)
    total = np.nansum(windows, axis=1)
    with np.errstate(divide="ignore", invalid="ignore"):
        scaled = total * SLEEP_DEBT_NIGHTS / n_valid
    debt = np.where(n_valid >= SLEEP_DEBT_MIN_NIGHTS, scaled, np.nan)
    return pd.Series(debt[positions], index=sleep_s.index, dtype=float, name="sleep_debt_7")


def with_baselines(wellness: pd.DataFrame) -> pd.DataFrame:
    """`wellness` plus the §8 baseline columns and `sleep_debt_7` (§9). The input is not modified."""
    base = baselines(wellness)
    out = wellness.copy()
    for column in base.columns:
        out[column] = base[column].to_numpy()
    sleep = (
        wellness["sleep_s"]
        if "sleep_s" in wellness.columns
        else pd.Series(np.nan, index=wellness.index, dtype=float)
    )
    median = pd.Series(base["sleep_s_median28"].to_numpy(), index=wellness.index)
    out["sleep_debt_7"] = sleep_debt_7(sleep, median).to_numpy()
    return out


# ---------------------------------------------------------------------------------------------------------
# helpers


def _trailing_median_mad(values: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Median and raw MAD over positions i−28 … i−1 of a gap-free daily array (NaN = no value)."""
    padded = np.concatenate([np.full(BASELINE_DAYS, np.nan), values[:-1]])
    windows = sliding_window_view(padded, BASELINE_DAYS)  # row i = days i−28 … i−1
    n_valid = np.sum(~np.isnan(windows), axis=1)
    enough = n_valid >= MIN_BASELINE_VALUES
    median = np.full(len(values), np.nan)
    mad = np.full(len(values), np.nan)
    if enough.any():
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", RuntimeWarning)  # all-NaN rows are masked out anyway
            w = windows[enough]
            med = np.nanmedian(w, axis=1)
            median[enough] = med
            mad[enough] = np.nanmedian(np.abs(w - med[:, None]), axis=1)
    return median, mad


def _date_index(index: pd.Index) -> list[date]:
    """The index as `datetime.date` values (accepts `date` objects or timestamps); unique dates only."""
    days = [pd.Timestamp(v).date() for v in index]
    if len(set(days)) != len(days):
        raise ValueError("wellness index has duplicate dates")
    return days


def _full_range(days: list[date]) -> pd.DatetimeIndex:
    return pd.date_range(min(days), max(days), freq="D")


def _positions(full: pd.DatetimeIndex, days: list[date]) -> np.ndarray:
    return np.array([(d - full[0].date()).days for d in days], dtype=int)


def _align(series: pd.Series, full: pd.DatetimeIndex) -> np.ndarray:
    """Values of a date-indexed series on the days of `full` (NaN where absent)."""
    out = np.full(len(full), np.nan)
    if len(series) == 0:
        return out
    days = _date_index(series.index)
    offsets = np.array([(d - full[0].date()).days for d in days], dtype=int)
    inside = (offsets >= 0) & (offsets < len(full))
    out[offsets[inside]] = _numeric(series)[inside]
    return out


def _numeric(column: pd.Series) -> np.ndarray:
    """Float array, NaN for null / non-numeric (handles nullable Int64 and object columns)."""
    return pd.to_numeric(column, errors="coerce").astype(float).to_numpy()
