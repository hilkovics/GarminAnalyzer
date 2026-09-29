"""Best efforts and threshold proposals – METRICS §6.2, §6.3 (phase 4).

# METRICS §6.2
Windows `W ∈ {60, 300, 600, 1200, 1800, 3600} s`. For each activity and W: max over all positions of the
mean of `gap_speed` (run) or `speed` (bike, W ≥ 300 only) over a contiguous window of moving samples
(no pause inside). Also **HR best efforts**: max rolling-mean HR over `{1200, 1800, 3600} s`.
Curves: best per W over trailing 90 days and all-time.
(Clarified 2026-09-29, phase 4: "contiguous" = consecutive kept samples whose `t` increases by exactly 1;
every sample in the window must have a valid value (a NaN breaks the window). The effort's distance is the
cumulative-distance difference across the window, null if unavailable. HR efforts for all sports.
Trailing 90 days = `local_date` in [today − 89, today].)

# METRICS §6.3
- `threshold_speed_est` = max over trailing 90 days of best 1800 s gap_speed (fallback: 0.95 · best 1200 s).
  Propose when it differs from current by `> 2 %`.
- `lthr_est` (per sport) = max over trailing 90 days of the 1800 s HR best effort from activities with
  `if_pace ≥ 0.95` (run) or with the top-decile hrTSS/h (bike). Propose when `|Δ| > 3 bpm`.
(Clarified 2026-09-29, phase 4: "current" = the threshold valid today. Bikes: activities whose
`hrtss / (moving_s / 3600)` is ≥ the 90th percentile (at least one activity) among the sport's activities
of the window. No qualifying data → no proposal. Without a current threshold the estimate is always
proposed. Proposals round: speed to 0.01 m/s, LTHR to whole bpm.)

Interpretation choices (literal where the text is silent):
- The effort distance is `distance[last] − distance[first]` of the window's samples (W − 1 seconds of
  travel under the §0.4 convention); `start_t` is `t` of the first sample. Ties → the earliest position.
- HR best efforts use raw HR (no §0.6 lag: nothing is paired with speed). Walking samples count (§6.2 does
  not exclude them).
- `best_per_window` and the proposals ignore rows dated after `today`; ties → the earliest `local_date`.
- The 2 % / 3 bpm rules compare the rounded estimate with `current` (so the reported numbers agree with
  the decision), with a 1e-9 tolerance against floating-point residue at the exact boundary.
- Percentile: numpy's default linear interpolation over the rides with a valid hrTSS/h.

Pure functions, no I/O.
"""

import math
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
import pandas as pd

from training.metrics.preprocess import SPORTS, Preprocessed

EFFORT_WINDOWS: tuple[int, ...] = (60, 300, 600, 1200, 1800, 3600)  # §6.2, s
HR_EFFORT_WINDOWS: tuple[int, ...] = (1200, 1800, 3600)  # §6.2, s
BIKE_MIN_WINDOW = 300  # §6.2: bike speed efforts only for W ≥ 300 s
TRAILING_DAYS = 90  # §6.2 / §6.3

SPEED_WINDOW = 1800  # §6.3 threshold_speed_est
SPEED_FALLBACK_WINDOW = 1200  # §6.3 fallback
SPEED_FALLBACK_FACTOR = 0.95  # §6.3 fallback: 0.95 · best 1200 s
SPEED_PROPOSE_REL = 0.02  # §6.3: propose when > 2 %
LTHR_WINDOW = 1800  # §6.3 lthr_est
LTHR_PROPOSE_BPM = 3.0  # §6.3: propose when |Δ| > 3 bpm
RUN_MIN_IF_PACE = 0.95  # §6.3 run activity filter
BIKE_TOP_PERCENTILE = 90.0  # §6.3 bike: top decile of hrTSS/h
_EPS = 1e-9

BEST_COLUMNS: list[str] = ["kind", "window_s", "value", "local_date", "activity_id"]


@dataclass(frozen=True)
class Effort:
    """One best effort of one activity (METRICS §6.2)."""

    kind: str  # "gap_speed" (run) | "speed" (bike, W ≥ 300) | "hr" (all sports)
    window_s: int
    value: float  # m/s or bpm
    distance_m: float | None  # distance covered in the window; None for hr efforts / no distance
    start_t: int


@dataclass(frozen=True)
class ThresholdProposal:
    """A threshold estimate and whether to propose it (METRICS §6.3; never auto-applied)."""

    sport: str
    field: str  # "threshold_speed" | "lthr"
    current: float | None
    estimate: float
    change: float  # relative (speed) or bpm (lthr) difference vs current; NaN without current
    propose: bool
    basis: str


# ---------------------------------------------------------------- §6.2 best efforts


def best_efforts(prep: Preprocessed, sport: str) -> list[Effort]:
    """METRICS §6.2: best efforts of one activity.

    run → `gap_speed` over all `EFFORT_WINDOWS`; bike → `speed` over the windows ≥ `BIKE_MIN_WINDOW`;
    other → none. Plus HR efforts over `HR_EFFORT_WINDOWS` for every sport. Windows that do not fit in
    any contiguous valid stretch are omitted. Order: speed efforts by window, then HR efforts by window.
    """
    if sport not in SPORTS:
        raise ValueError(f"sport must be one of {SPORTS}, got {sport!r}")
    s = prep.samples
    if s.empty:
        return []
    t = np.asarray(s["t"], dtype=np.int64)
    distance = np.asarray(s["distance"], dtype=float)
    out: list[Effort] = []
    if sport == "run":
        gap = np.asarray(s["gap_speed"], dtype=float)
        out += _window_bests("gap_speed", t, gap, EFFORT_WINDOWS, distance)
    elif sport == "bike":
        windows = tuple(w for w in EFFORT_WINDOWS if w >= BIKE_MIN_WINDOW)
        out += _window_bests("speed", t, np.asarray(s["speed"], dtype=float), windows, distance)
    out += _window_bests("hr", t, np.asarray(s["hr"], dtype=float), HR_EFFORT_WINDOWS, None)
    return out


def _window_bests(
    kind: str, t: np.ndarray, values: np.ndarray, windows: tuple[int, ...], distance: np.ndarray | None
) -> list[Effort]:
    """Max mean of `values` over each window length, over contiguous (Δt == 1), all-valid stretches."""
    run_len = _run_lengths(t, values)
    csum = np.concatenate([[0.0], np.cumsum(np.where(np.isnan(values), 0.0, values))])
    out: list[Effort] = []
    for w in windows:
        ends = np.flatnonzero(run_len >= w)
        if ends.size == 0:
            continue
        means = (csum[ends + 1] - csum[ends + 1 - w]) / w
        end = int(ends[int(np.argmax(means))])
        start = end - w + 1
        dist: float | None = None
        if distance is not None:
            d = float(distance[end] - distance[start])
            dist = None if math.isnan(d) else d
        value = float(np.mean(values[start : end + 1]))
        out.append(Effort(kind=kind, window_s=w, value=value, distance_m=dist, start_t=int(t[start])))
    return out


def _run_lengths(t: np.ndarray, values: np.ndarray) -> np.ndarray:
    """`run_len[i]` = length of the contiguous valid stretch ending at sample i (0 where invalid).

    A stretch continues from i−1 to i only if both are valid and `t[i] − t[i−1] == 1` (§6.2 clarified).
    """
    n = len(values)
    valid = ~np.isnan(values)
    cont = np.zeros(n, dtype=bool)
    if n > 1:
        cont[1:] = (np.diff(t) == 1) & valid[1:] & valid[:-1]
    idx = np.arange(n)
    start = np.maximum.accumulate(np.where(cont, 0, idx))
    return np.where(valid, idx - start + 1, 0)


# ---------------------------------------------------------------- §6.2 curves


def best_per_window(efforts: pd.DataFrame, *, today: date, days: int | None = TRAILING_DAYS) -> pd.DataFrame:
    """METRICS §6.2 curves: the best `value` per (kind, window_s) over `local_date` in
    [today − (days − 1), today], or all-time (≤ today) with `days=None`.

    Input columns `local_date, kind, window_s, value` (+ optional `activity_id`). Output columns
    `BEST_COLUMNS`, one row per (kind, window_s), sorted by kind and window; `local_date` as `date`;
    `activity_id` None when the input has none. Ties → the earliest date.
    """
    df = _in_window(efforts, today, days)
    df = df[pd.to_numeric(df["value"], errors="coerce").notna()]
    if df.empty:
        return pd.DataFrame(columns=BEST_COLUMNS)
    if "activity_id" not in df.columns:
        df = df.assign(activity_id=pd.Series([None] * len(df), index=df.index, dtype=object))
    df = df.sort_values(
        ["kind", "window_s", "value", "local_date"], ascending=[True, True, False, True], kind="stable"
    )
    best = df.drop_duplicates(["kind", "window_s"], keep="first")
    return best[BEST_COLUMNS].reset_index(drop=True)


def _local_dates(column: pd.Series) -> pd.Series:
    """A date-like column (date / Timestamp / ISO string) as Python `date` objects."""
    return pd.to_datetime(column).dt.date


def _in_window(frame: pd.DataFrame, today: date, days: int | None) -> pd.DataFrame:
    """Rows with `local_date` in [today − (days − 1), today] (all ≤ today for `days=None`), as `date`s."""
    df = frame.copy()
    df["local_date"] = _local_dates(df["local_date"])
    keep = df["local_date"] <= today
    if days is not None:
        keep &= df["local_date"] >= today - timedelta(days=days - 1)
    return df[keep.astype(bool)]


# ---------------------------------------------------------------- §6.3 proposals


def propose_threshold_speed(
    efforts: pd.DataFrame, *, current: float | None, today: date
) -> ThresholdProposal | None:
    """METRICS §6.3 `threshold_speed_est` from run `gap_speed` efforts (`local_date, window_s, value`).

    Best 1800 s of the trailing 90 days, else 0.95 · best 1200 s; None without either. Rounded to 0.01 m/s;
    `change` = estimate / current − 1; proposed when `|change| > 2 %` or without a current value.
    """
    df = _in_window(efforts, today, TRAILING_DAYS)
    if "kind" in df.columns:
        df = df[df["kind"] == "gap_speed"]
    row = _best_row(df, SPEED_WINDOW)
    if row is not None:
        raw = float(row["value"])
        basis = f"best {SPEED_WINDOW} s GAP ({row['local_date'].isoformat()})"
    else:
        row = _best_row(df, SPEED_FALLBACK_WINDOW)
        if row is None:
            return None
        raw = SPEED_FALLBACK_FACTOR * float(row["value"])
        basis = (
            f"{SPEED_FALLBACK_FACTOR} · best {SPEED_FALLBACK_WINDOW} s GAP ({row['local_date'].isoformat()}),"
            f" no {SPEED_WINDOW} s effort in {TRAILING_DAYS} days"
        )
    estimate = _round_half_up(raw, 2)
    if _has_value(current) and current > 0:
        change = estimate / current - 1.0
        propose = abs(change) > SPEED_PROPOSE_REL + _EPS
    else:
        change, propose = math.nan, True
    return ThresholdProposal(
        sport="run",
        field="threshold_speed",
        current=current,
        estimate=estimate,
        change=change,
        propose=propose,
        basis=basis,
    )


def propose_lthr(
    sport: str, efforts: pd.DataFrame, activities: pd.DataFrame, *, current: float | None, today: date
) -> ThresholdProposal | None:
    """METRICS §6.3 `lthr_est` for "run" or "bike".

    `efforts`: HR efforts (`activity_id, local_date, value`; rows of another kind / window are ignored when
    those columns exist). `activities`: this sport's activities (`activity_id, local_date, if_pace, hrtss,
    moving_s`; filtered by a `sport` column if present). Qualifying activities of the trailing 90 days:
    run `if_pace ≥ 0.95`; bike hrTSS/h ≥ its 90th percentile. Estimate = max 1800 s HR effort among them,
    rounded to whole bpm; `change` = estimate − current; proposed when `|change| > 3` or without current.
    """
    if sport not in ("run", "bike"):
        raise ValueError(f"lthr proposals are defined for 'run' and 'bike', got {sport!r}")
    eff = _in_window(efforts, today, TRAILING_DAYS)
    if "kind" in eff.columns:
        eff = eff[eff["kind"] == "hr"]
    if "window_s" in eff.columns:
        eff = eff[eff["window_s"] == LTHR_WINDOW]
    eff = eff[pd.to_numeric(eff["value"], errors="coerce").notna()]
    acts = _in_window(activities, today, TRAILING_DAYS)
    if "sport" in acts.columns:
        acts = acts[acts["sport"] == sport]

    if sport == "run":
        qualifying = acts[pd.to_numeric(acts["if_pace"], errors="coerce") >= RUN_MIN_IF_PACE]
        selection = f"{len(qualifying)} run(s) with if_pace ≥ {RUN_MIN_IF_PACE}"
    else:
        hrtss = pd.to_numeric(acts["hrtss"], errors="coerce").to_numpy(dtype=float)
        moving = pd.to_numeric(acts["moving_s"], errors="coerce").to_numpy(dtype=float)
        with np.errstate(divide="ignore", invalid="ignore"):
            rate = np.where(moving > 0, hrtss / (moving / 3600.0), np.nan)
        valid = np.isfinite(rate)
        if not valid.any():
            return None
        cutoff = min(float(np.percentile(rate[valid], BIKE_TOP_PERCENTILE)), float(rate[valid].max()))
        qualifying = acts[valid & (rate >= cutoff)]
        selection = f"{len(qualifying)} top-decile hrTSS/h ride(s) of {int(valid.sum())}"

    eff = eff[eff["activity_id"].isin(qualifying["activity_id"])]
    row = _best_row(eff, None)
    if row is None:
        return None
    estimate = _round_half_up(float(row["value"]), 0)
    if _has_value(current):
        change = estimate - float(current)
        propose = abs(change) > LTHR_PROPOSE_BPM + _EPS
    else:
        change, propose = math.nan, True
    return ThresholdProposal(
        sport=sport,
        field="lthr",
        current=current,
        estimate=estimate,
        change=change,
        propose=propose,
        basis=f"max {LTHR_WINDOW} s HR effort ({row['local_date'].isoformat()}) of {selection}",
    )


def _best_row(df: pd.DataFrame, window_s: int | None) -> pd.Series | None:
    """Row with the highest valid `value` (for `window_s`, if given); ties → earliest `local_date`."""
    if window_s is not None:
        df = df[df["window_s"] == window_s]
    values = pd.to_numeric(df["value"], errors="coerce")
    df = df.assign(value=values)[values.notna()]
    if df.empty:
        return None
    return df.sort_values(["value", "local_date"], ascending=[False, True], kind="stable").iloc[0]


def _round_half_up(x: float, digits: int) -> float:
    """§6.3 proposal rounding (half up, not banker's rounding)."""
    scale = 10.0**digits
    return math.floor(x * scale + 0.5) / scale


def _has_value(x: float | None) -> bool:
    return x is not None and math.isfinite(float(x))
