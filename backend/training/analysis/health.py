"""Health trends and relationships (METRICS §12): daily metrics, rolling means and the personal normal band,
monthly means, the recent 28-day change, and relationships between deviations from the normal.

Pure functions over a date-indexed frame with one column per §12.1 metric (a full daily calendar is built
inside; missing days are NaN). No I/O.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta
from itertools import combinations

import numpy as np
import pandas as pd
from scipy import stats


@dataclass(frozen=True)
class MetricInfo:
    key: str
    label: str  # Slovak
    unit: str
    better: str | None  # "up" | "down" | None
    family: str | None


METRICS: tuple[MetricInfo, ...] = (
    MetricInfo("sleep_s", "Spánok", "s", "up", "sleep"),
    MetricInfo("deep_s", "Hlboký spánok", "s", "up", "sleep"),
    MetricInfo("rem_s", "REM spánok", "s", "up", "sleep"),
    MetricInfo("awake_s", "Bdenie v noci", "s", "down", "sleep"),
    MetricInfo("sleep_score", "Skóre spánku", "", "up", "sleep"),
    MetricInfo("sleep_stress", "Stres v spánku", "", "down", None),
    MetricInfo("respiration_sleep", "Dýchanie v spánku", "dych/min", None, None),
    MetricInfo("restless_count", "Nepokojné chvíle", "", "down", None),
    MetricInfo("rhr", "Pokojový tep", "bpm", "down", None),
    MetricInfo("body_battery_wake", "Body Battery ráno", "", "up", "battery"),
    MetricInfo("bb_charge", "Nabitie Body Battery v noci", "", "up", "battery"),
    MetricInfo("bb_high", "Najvyššia Body Battery", "", "up", "battery"),
    MetricInfo("stress_avg", "Denný stres", "", "down", "stress"),
    MetricInfo("stress_high_s", "Čas vo vysokom strese", "s", "down", "stress"),
    MetricInfo("intensity_min", "Intenzívne minúty", "min", None, "activity"),
    MetricInfo("steps", "Kroky", "", None, "activity"),
    MetricInfo("load", "Tréningová záťaž", "TSS-ekv.", None, "activity"),
)
BY_KEY = {m.key: m for m in METRICS}

MEAN7_MIN, MEAN28_MIN, BASELINE_MIN, MONTH_MIN = 4, 14, 7, 10
WINDOW = 28
CHANGE_MIN = 14
P_NOTABLE = 0.05
MIN_N = 30
RHO_FINDING = 0.2
BH_Q = 0.05
SPEARMAN_SE = 1.03
CONTRAST_MIN = 5


def calendar(frame: pd.DataFrame, end: date | None = None) -> pd.DataFrame:
    """`frame` reindexed to every day from its first day to `end` (or its last day), index of `date`s."""
    if frame.empty:
        return frame
    days = sorted(pd.to_datetime(pd.Index(frame.index)).date)
    last = end or days[-1]
    index = [days[0] + timedelta(days=i) for i in range((last - days[0]).days + 1)]
    out = frame.copy()
    out.index = pd.to_datetime(pd.Index(out.index)).date
    return out.reindex(index).apply(pd.to_numeric, errors="coerce").astype(float)


# --- §12.2 trends -------------------------------------------------------------------------------------------


def _mad(window: np.ndarray) -> float:
    valid = window[~np.isnan(window)]
    if len(valid) < BASELINE_MIN:
        return math.nan
    return float(np.median(np.abs(valid - np.median(valid))))


def trends(series: pd.Series) -> pd.DataFrame:
    """§12.2 on a daily series: value, mean7, mean28 (trailing, including the day), median28 / mad28 of the
    28 days before the day (the normal band) and pct = mean7 relative to median28 in %."""
    s = series.astype(float)
    previous = s.shift(1)
    mean7 = s.rolling(7, min_periods=MEAN7_MIN).mean()
    median28 = previous.rolling(WINDOW, min_periods=BASELINE_MIN).median()
    base = median28.abs().where(median28 != 0)
    return pd.DataFrame(
        {
            "value": s,
            "mean7": mean7,
            "mean28": s.rolling(WINDOW, min_periods=MEAN28_MIN).mean(),
            "median28": median28,
            "mad28": previous.rolling(WINDOW, min_periods=1).apply(_mad, raw=True),
            "pct": (mean7 - median28) / base * 100.0,
        },
        index=s.index,
    )


def monthly(series: pd.Series) -> pd.Series:
    """§12.2 calendar-month means (≥ 10 values), indexed by "YYYY-MM"."""
    s = series.astype(float).dropna()
    if s.empty:
        return pd.Series(dtype=float)
    keys = [f"{d.year:04d}-{d.month:02d}" for d in s.index]
    grouped = s.groupby(keys)
    means = grouped.mean()
    return means[grouped.count() >= MONTH_MIN]


@dataclass(frozen=True)
class RecentChange:
    recent: float | None
    previous: float | None
    diff: float | None
    pct: float | None
    p: float | None
    notable: bool
    direction: str | None  # "better" | "worse" | None


def recent_change(series: pd.Series, today: date, better: str | None) -> RecentChange:
    """§12.2: the last 28 days vs the 28 before (≥ 14 values each), Mann–Whitney U two-sided."""
    s = series.astype(float)
    dates = pd.Index(s.index)
    recent = s[(dates >= today - timedelta(days=27)) & (dates <= today)].dropna()
    previous = s[(dates >= today - timedelta(days=55)) & (dates <= today - timedelta(days=28))].dropna()
    if len(recent) < CHANGE_MIN or len(previous) < CHANGE_MIN:
        return RecentChange(None, None, None, None, None, False, None)
    a, b = float(recent.mean()), float(previous.mean())
    diff = a - b
    if np.ptp(np.concatenate([recent.to_numpy(), previous.to_numpy()])) == 0:
        p = 1.0
    else:
        p = float(stats.mannwhitneyu(recent, previous, alternative="two-sided").pvalue)
    notable = p < P_NOTABLE
    direction = None
    if notable and better is not None and diff != 0:
        direction = "better" if (diff > 0) == (better == "up") else "worse"
    return RecentChange(a, b, diff, diff / b if b else None, p, notable, direction)


# --- §12.3 relationships ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Relationship:
    x: str
    y: str
    lag: int  # 0 = same day, 1 = x on D, y on D + 1
    n: int
    rho: float | None
    ci_low: float | None
    ci_high: float | None
    p: float | None
    finding: bool = False
    contrast: float | None = None  # mean y (raw) for top − bottom quartile of x deviation


def deviations(frame: pd.DataFrame) -> pd.DataFrame:
    """§12.3: value − median28 of every column (on a full daily calendar)."""
    return pd.DataFrame(
        {c: frame[c] - trends(frame[c])["median28"] for c in frame.columns}, index=frame.index
    )


def _pairs(columns: list[str]) -> list[tuple[str, str, int]]:
    out = []
    for x, y in combinations(columns, 2):
        fx, fy = BY_KEY[x].family if x in BY_KEY else None, BY_KEY[y].family if y in BY_KEY else None
        if fx is None or fx != fy:
            out.append((x, y, 0))
    out += [(x, y, 1) for x in columns for y in columns if x != y]
    return out


def _fisher_ci(rho: float, n: int) -> tuple[float, float]:
    clipped = min(max(rho, -0.999999), 0.999999)
    z, se = math.atanh(clipped), SPEARMAN_SE / math.sqrt(n - 3)
    return math.tanh(z - 1.96 * se), math.tanh(z + 1.96 * se)


def _contrast(xd: np.ndarray, y: np.ndarray) -> float | None:
    q1, q3 = np.quantile(xd, [0.25, 0.75])
    top, bottom = y[xd >= q3], y[xd <= q1]
    if len(top) < CONTRAST_MIN or len(bottom) < CONTRAST_MIN or q1 == q3:
        return None
    return float(top.mean() - bottom.mean())


def benjamini_hochberg(pvalues: list[float], q: float = BH_Q) -> list[bool]:
    """Which hypotheses pass the Benjamini–Hochberg procedure at level `q`."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    passed = [False] * m
    last = -1
    for rank, i in enumerate(order, start=1):
        if pvalues[i] <= q * rank / m:
            last = rank
    for rank, i in enumerate(order, start=1):
        passed[i] = rank <= last
    return passed


def relationships(frame: pd.DataFrame) -> list[Relationship]:
    """§12.3 on a full daily calendar frame (one column per metric): every pair with n ≥ 30, findings
    flagged (|ρ| ≥ 0.2 and BH at q = 0.05) and sorted first by |ρ|."""
    dev = deviations(frame)
    columns = [c for c in frame.columns if dev[c].notna().any()]
    raw: list[Relationship] = []
    for x, y, lag in _pairs(columns):
        xd = dev[x].to_numpy()
        yd = dev[y].shift(-lag).to_numpy()
        yv = frame[y].shift(-lag).to_numpy()
        ok = ~np.isnan(xd) & ~np.isnan(yd) & ~np.isnan(yv)
        n = int(ok.sum())
        if n < MIN_N or np.ptp(xd[ok]) == 0 or np.ptp(yd[ok]) == 0:
            continue
        rho, p = stats.spearmanr(xd[ok], yd[ok])
        low, high = _fisher_ci(float(rho), n)
        raw.append(
            Relationship(x, y, lag, n, float(rho), low, high, float(p), contrast=_contrast(xd[ok], yv[ok]))
        )
    passed = benjamini_hochberg([r.p for r in raw if r.p is not None])
    out = [
        Relationship(**{**r.__dict__, "finding": ok and abs(r.rho or 0.0) >= RHO_FINDING})
        for r, ok in zip(raw, passed, strict=True)
    ]
    return sorted(out, key=lambda r: (not r.finding, -abs(r.rho or 0.0)))
