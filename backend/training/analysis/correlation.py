"""Sleep ↔ performance correlation dataset and statistics – METRICS §9 (phase 5).

# METRICS §9 (with the binding "Clarified 2026-09-29 (phase 5, proposed)" block):
#   Per sport (run, bike; `other` excluded). Qualifying day D: ≥ 1 activity of that sport with at least one
#   non-null outcome; the longest `moving_s` one is used.
#   Outcomes: ef, decoupling_pct, pace_at_ref_hr_day (run only),
#     rpe_residual = rpe − rpe_expected, rpe_expected = 1 + 9 · clamp((IF_primary − 0.5) / 0.7, 0, 1),
#     IF_primary = if_pace when load_method = rTSS, else if_hr; null if either value is missing.
#   Predictors: sleep_s, deep_s, rem_s, sleep_score, rhr, body_battery_wake, each as lag0 = row D,
#     lag1 = row D−1, mean3 = mean of rows D−2 … D (≥ 2 valid values); plus sleep_debt_7 (lag0 only).
#   Controls: TSB[D], ATL[D−1], daily_load[D−1].
#   n = rows with predictor and outcome non-null (+ all controls for the partial); n < 30 →
#     insufficient_data with ρ, CI, p and contrast null.
#   Spearman via scipy.stats.spearmanr (t-approximation p). Partial: OLS with intercept on the three
#     controls for both variables, Spearman on the residuals (p not df-adjusted).
#   Bootstrap: 1000 resamples with replacement, numpy.random.default_rng(seed = 0); the partial re-runs the
#     residualization per resample; percentile CI (2.5 %, 97.5 %); NaN resamples dropped, > 10 % NaN →
#     CI null.
#   Quartile contrast: bottom = x ≤ Q1, top = x ≥ Q3 (numpy linear quantiles), mean(y | top) − mean(y |
#     bottom), not partialled, bootstrap CI on the same resamples, ≥ 5 rows per group else null.
#   Findings sorted by |partial ρ| (raw ρ if the partial is null); CI containing 0 → uncertain.

The caller passes precomputed wellness columns (including `sleep_debt_7`, §8 baselines) and the §4 daily
series; this module only aligns and correlates. Pure functions, no I/O.
"""

from dataclasses import dataclass, field, fields
from typing import Literal

import numpy as np
import pandas as pd

from training.analysis.stats import (
    Memo,
    centered_ranks,
    finite_or_none,
    is_uncertain,
    ols_projector,
    ols_residuals,
    pearson_of_ranks,
    percentile_ci,
    quartile_contrast,
    quartile_contrast_rows,
    quartile_groups,
    resample_indices,
    spearman,
)

MIN_N = 30
N_BOOT = 1000
SPORTS = ("run", "bike")
BASE_PREDICTORS = ("sleep_s", "deep_s", "rem_s", "sleep_score", "rhr", "body_battery_wake")
VARIANTS = ("lag0", "lag1", "mean3")
EXTRA_PREDICTORS = ("sleep_debt_7",)
OUTCOMES = ("ef", "decoupling_pct", "pace_at_ref_hr_day", "rpe_residual")
RUN_ONLY_OUTCOMES = ("pace_at_ref_hr_day",)
CONTROLS = ("tsb", "atl_prev", "load_prev")

MEAN3_MIN_VALID = 2  # METRICS §9: mean3 "needs ≥ 2 valid values"

ACTIVITY_COLUMNS = (
    *("activity_id", "local_date", "sport", "moving_s", "load_method", "if_hr", "if_pace"),
    *("ef", "decoupling_pct", "pace_at_ref_hr_day", "rpe"),
)
DAILY_COLUMNS = ("load_total", "atl", "tsb")

Status = Literal["ok", "insufficient_data"]


def predictor_columns() -> list[str]:
    """Predictor columns: `{base}_{variant}` for every base predictor and variant, plus sleep_debt_7."""
    return [f"{p}_{v}" for p in BASE_PREDICTORS for v in VARIANTS] + list(EXTRA_PREDICTORS)


def dataset_columns() -> list[str]:
    """Column order of `build_dataset` output."""
    return ["activity_id", *OUTCOMES, *predictor_columns(), *CONTROLS]


def outcomes_for(sport: str) -> tuple[str, ...]:
    """Outcomes applicable to a sport – METRICS §9: `pace_at_ref_hr_day` is run only."""
    _check_sport(sport)
    return OUTCOMES if sport == "run" else tuple(o for o in OUTCOMES if o not in RUN_ONLY_OUTCOMES)


def rpe_expected(if_primary: float) -> float:
    """`1 + 9 · clamp((IF_primary − 0.5) / 0.7, 0, 1)` – METRICS §9. NaN in → NaN out."""
    return float(_rpe_expected(np.asarray(if_primary, dtype=float)))


def _rpe_expected(if_primary: np.ndarray) -> np.ndarray:
    # METRICS §9: rpe_expected = 1 + 9 · clamp((IF_primary − 0.5) / 0.7, 0, 1)
    return 1.0 + 9.0 * np.clip((if_primary - 0.5) / 0.7, 0.0, 1.0)


# --------------------------------------------------------------------------------------------------
# dataset


def build_dataset(
    activities: pd.DataFrame, wellness: pd.DataFrame, daily: pd.DataFrame, sport: str
) -> pd.DataFrame:
    """Day-level correlation dataset for one sport – METRICS §9 (clarified).

    `activities`: one row per activity with `ACTIVITY_COLUMNS` (`local_date` a `datetime.date`, `rpe`
    nullable). `wellness`: date-indexed (possibly sparse) with the `BASE_PREDICTORS` and a precomputed
    `sleep_debt_7`; missing wellness columns count as all-null. `daily`: date-indexed §4 series with
    `load_total, atl, tsb`.

    Returns one row per qualifying day, indexed by a sorted daily `DatetimeIndex` named `date` (midnight
    timestamps, as in `metrics.pmc`), with the columns of `dataset_columns()`. For bike,
    `pace_at_ref_hr_day` is all NaN. Lags are by calendar day: lag1 = wellness row D−1, mean3 = rows
    D−2 … D (≥ 2 valid). Controls: tsb = tsb[D], atl_prev = atl[D−1], load_prev = load_total[D−1].
    """
    _check_sport(sport)
    _require_columns(activities, ACTIVITY_COLUMNS, "activities")
    _require_columns(daily, DAILY_COLUMNS, "daily")

    chosen = _pick_activities(activities, sport)
    dates = pd.DatetimeIndex(chosen.index, name="date")
    out = pd.DataFrame(index=dates)
    out["activity_id"] = chosen["activity_id"]
    for outcome in OUTCOMES:
        out[outcome] = chosen[outcome].astype("float64")

    wellness_days = _day_frame(wellness, [*BASE_PREDICTORS, *EXTRA_PREDICTORS])
    if len(dates):
        calendar = pd.date_range(dates.min() - pd.Timedelta(days=2), dates.max(), freq="D", name="date")
        wellness_days = wellness_days.reindex(calendar)
    for base in BASE_PREDICTORS:
        series = wellness_days[base]
        out[f"{base}_lag0"] = series.reindex(dates).to_numpy()
        out[f"{base}_lag1"] = series.shift(1).reindex(dates).to_numpy()
        out[f"{base}_mean3"] = series.rolling(3, min_periods=MEAN3_MIN_VALID).mean().reindex(dates).to_numpy()
    for extra in EXTRA_PREDICTORS:
        out[extra] = wellness_days[extra].reindex(dates).to_numpy()

    daily_days = _day_frame(daily, list(DAILY_COLUMNS))
    previous = dates - pd.Timedelta(days=1)
    out["tsb"] = daily_days["tsb"].reindex(dates).to_numpy()
    out["atl_prev"] = daily_days["atl"].reindex(previous).to_numpy()
    out["load_prev"] = daily_days["load_total"].reindex(previous).to_numpy()
    return out[dataset_columns()]


def _pick_activities(activities: pd.DataFrame, sport: str) -> pd.DataFrame:
    """Per day, the longest-`moving_s` activity of `sport` with ≥ 1 non-null outcome – METRICS §9."""
    acts = activities.loc[activities["sport"] == sport]
    load_method = acts["load_method"].tolist()
    is_rtss = np.array([isinstance(m, str) and m.lower() == "rtss" for m in load_method], dtype=bool)
    # METRICS §9 (clarified): IF_primary = if_pace when load_method = rTSS, else if_hr.
    if_primary = np.where(is_rtss, _numeric(acts["if_pace"]), _numeric(acts["if_hr"]))
    frame = pd.DataFrame(
        {
            "activity_id": acts["activity_id"].to_numpy(),
            "date": _to_days(acts["local_date"]),
            "moving_s": _numeric(acts["moving_s"]),
            "ef": _numeric(acts["ef"]),
            "decoupling_pct": _numeric(acts["decoupling_pct"]),
            "pace_at_ref_hr_day": (
                _numeric(acts["pace_at_ref_hr_day"]) if sport == "run" else np.full(len(acts), np.nan)
            ),
            "rpe_residual": _numeric(acts["rpe"]) - _rpe_expected(if_primary),
        }
    )
    qualifying = frame[list(OUTCOMES)].notna().any(axis=1) & frame["date"].notna()
    frame = frame.loc[qualifying].sort_values(
        ["date", "moving_s", "activity_id"], ascending=[True, False, True], na_position="last"
    )
    return frame.drop_duplicates("date", keep="first").set_index("date")


def _day_frame(frame: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """Numeric copy of `columns` (missing → NaN) re-indexed by midnight timestamps."""
    out = pd.DataFrame(
        {c: _numeric(frame[c]) if c in frame.columns else np.full(len(frame), np.nan) for c in columns},
        index=pd.DatetimeIndex(_to_days(frame.index), name="date"),
    )
    if out.index.has_duplicates:
        raise ValueError("date index must be unique")
    return out


def _to_days(values: pd.Series | pd.Index) -> np.ndarray:
    return pd.DatetimeIndex(pd.to_datetime(values)).normalize().as_unit("ns").to_numpy()


def _numeric(values: pd.Series) -> np.ndarray:
    return pd.to_numeric(values, errors="coerce").to_numpy(dtype="float64", na_value=np.nan)


def _require_columns(frame: pd.DataFrame, columns: tuple[str, ...], name: str) -> None:
    missing = [c for c in columns if c not in frame.columns]
    if missing:
        raise ValueError(f"{name} is missing columns: {missing}")


def _check_sport(sport: str) -> None:
    if sport not in SPORTS:
        raise ValueError(f"sport must be one of {SPORTS}, got {sport!r}")


# --------------------------------------------------------------------------------------------------
# statistics


@dataclass(frozen=True)
class CorrelationResult:
    """One (sport, predictor, outcome) finding – METRICS §9. Null statistics are `None`."""

    sport: str
    predictor: str
    outcome: str
    n: int
    status: Status
    rho: float | None
    p: float | None
    ci_low: float | None
    ci_high: float | None
    partial_n: int | None
    partial_rho: float | None
    partial_p: float | None
    partial_ci_low: float | None
    partial_ci_high: float | None
    q_contrast: float | None
    q_ci_low: float | None
    q_ci_high: float | None
    q_n_bottom: int | None
    q_n_top: int | None
    uncertain: bool

    @property
    def headline_rho(self) -> float | None:
        """Partial ρ if not null, else the raw ρ – METRICS §9 (findings sort key)."""
        return self.partial_rho if self.partial_rho is not None else self.rho


def correlate(
    x: pd.Series | np.ndarray,
    y: pd.Series | np.ndarray,
    controls: pd.DataFrame | None,
    *,
    sport: str,
    predictor: str,
    outcome: str,
    n_boot: int = N_BOOT,
    seed: int = 0,
) -> CorrelationResult:
    """Spearman, partial Spearman, bootstrap CIs and quartile contrast of `y` on `x` – METRICS §9.

    `x`, `y` and the `controls` rows are aligned by position (equal length). `n` counts rows with `x` and
    `y` non-null; `partial_n` additionally needs every control (`None` without controls). Each bootstrap
    resamples its own rows with `resample_indices(size, n_boot, seed)` (`numpy.random.default_rng(seed)`),
    so the raw ρ and the quartile contrast share one resample matrix, and the partial uses the same one
    whenever the controls drop no row.
    """
    xa, ya = _as_float(x), _as_float(y)
    if len(xa) != len(ya):
        raise ValueError("x and y must have the same length")
    ca = None if controls is None else _controls_array(controls, len(xa))
    return _correlate(xa, ya, ca, _Pair(sport, predictor, outcome), _Bootstrap(n_boot, seed))


def correlations(
    dataset: pd.DataFrame, sport: str, *, n_boot: int = N_BOOT, seed: int = 0
) -> list[CorrelationResult]:
    """Every predictor × applicable outcome of a `build_dataset` frame – METRICS §9 (findings).

    Sorted by |headline ρ| descending (partial ρ, else raw); results with a null headline ρ (including
    `insufficient_data`) come last, in predictor/outcome order. Equal to calling `correlate` per pair; the
    pairs only share a memo of the one-sided bootstrap work.
    """
    outcomes = outcomes_for(sport)
    ca = _controls_array(dataset[list(CONTROLS)], len(dataset))
    values = {column: _numeric(dataset[column]) for column in (*predictor_columns(), *outcomes)}
    boot = _Bootstrap(n_boot, seed)
    results = [
        _correlate(values[predictor], values[outcome], ca, _Pair(sport, predictor, outcome), boot)
        for predictor in predictor_columns()
        for outcome in outcomes
    ]
    return sorted(results, key=_sort_key)


@dataclass(frozen=True)
class _Pair:
    sport: str
    predictor: str
    outcome: str


@dataclass
class _Bootstrap:
    """Resample settings plus the memo of one-sided bootstrap work shared by the pairs of one call."""

    n_boot: int
    seed: int
    memo: Memo = field(default_factory=lambda: Memo(len(OUTCOMES)))

    def indices(self, size: int) -> np.ndarray:
        return self.memo.get("idx", size, lambda: resample_indices(size, self.n_boot, self.seed))


_ID_FIELDS = ("sport", "predictor", "outcome", "n", "status", "partial_n", "uncertain")
_NULL_STATS = dict.fromkeys(f.name for f in fields(CorrelationResult) if f.name not in _ID_FIELDS)
_NO_PARTIAL: dict[str, float | None] = dict.fromkeys(
    ("partial_rho", "partial_p", "partial_ci_low", "partial_ci_high")
)


def _correlate(
    x: np.ndarray, y: np.ndarray, c: np.ndarray | None, pair: _Pair, boot: _Bootstrap
) -> CorrelationResult:
    """METRICS §9 statistics of one pair. Memo keys carry the column name and the row set."""
    memo = boot.memo
    mask = np.isfinite(x) & np.isfinite(y)
    n = int(mask.sum())
    partial_mask = None if c is None else mask & np.isfinite(c).all(axis=1)
    partial_n = None if partial_mask is None else int(partial_mask.sum())
    ids = {"sport": pair.sport, "predictor": pair.predictor, "outcome": pair.outcome, "n": n}
    if n < MIN_N:
        return CorrelationResult(
            **ids, status="insufficient_data", partial_n=partial_n, uncertain=True, **_NULL_STATS
        )

    rows = mask.tobytes()
    xs, ys = x[mask], y[mask]
    idx = boot.indices(n)

    rho, p = spearman(xs, ys)
    ci: tuple[float | None, float | None] = (None, None)
    if rho is not None:
        x_ranks = memo.get("x_ranks", (pair.predictor, rows), lambda: centered_ranks(xs[idx]))
        y_ranks = memo.get("y_ranks", (pair.outcome, rows), lambda: centered_ranks(ys[idx]))
        ci = percentile_ci(pearson_of_ranks(x_ranks, y_ranks))

    contrast, n_bottom, n_top = quartile_contrast_rows(xs[None, :], ys[None, :])
    q_contrast = finite_or_none(contrast[0]) if rho is not None else None  # §9: no contrast without ρ
    q_ci: tuple[float | None, float | None] = (None, None)
    if q_contrast is not None:
        groups = memo.get("x_quartiles", (pair.predictor, rows), lambda: quartile_groups(xs[idx]))
        q_ci = percentile_ci(quartile_contrast(groups, ys[idx]))

    partial = _NO_PARTIAL
    if c is not None and partial_mask is not None and partial_n is not None and partial_n >= MIN_N:
        partial = _partial(x, y, c, partial_mask, pair, boot)

    if partial["partial_rho"] is not None:
        headline = (partial["partial_rho"], partial["partial_ci_low"], partial["partial_ci_high"])
    else:
        headline = (rho, *ci)
    return CorrelationResult(
        **ids,
        status="ok",
        rho=rho,
        p=p,
        ci_low=ci[0],
        ci_high=ci[1],
        partial_n=partial_n,
        q_contrast=q_contrast,
        q_ci_low=q_ci[0],
        q_ci_high=q_ci[1],
        q_n_bottom=int(n_bottom[0]),
        q_n_top=int(n_top[0]),
        uncertain=is_uncertain(*headline),
        **partial,
    )


def _partial(
    x: np.ndarray, y: np.ndarray, c: np.ndarray, partial_mask: np.ndarray, pair: _Pair, boot: _Bootstrap
) -> dict[str, float | None]:
    """Partial Spearman: OLS-residualize on intercept + controls, Spearman on residuals – METRICS §9.

    The bootstrap re-runs the residualization on every resample.
    """
    memo, rows = boot.memo, partial_mask.tobytes()
    xp, yp, cp = x[partial_mask], y[partial_mask], c[partial_mask]
    point = memo.get("projector_point", rows, lambda: ols_projector(cp[None, :, :]))
    rho, p = spearman(ols_residuals(point, xp[None, :])[0], ols_residuals(point, yp[None, :])[0])
    if rho is None:
        return _NO_PARTIAL
    idx = boot.indices(len(xp))
    projector = memo.get("projector_boot", rows, lambda: ols_projector(cp[idx]))
    x_ranks = memo.get(
        "x_partial_ranks", (pair.predictor, rows), lambda: centered_ranks(ols_residuals(projector, xp[idx]))
    )
    y_ranks = memo.get(
        "y_partial_ranks", (pair.outcome, rows), lambda: centered_ranks(ols_residuals(projector, yp[idx]))
    )
    low, high = percentile_ci(pearson_of_ranks(x_ranks, y_ranks))
    return {"partial_rho": rho, "partial_p": p, "partial_ci_low": low, "partial_ci_high": high}


def _sort_key(result: CorrelationResult) -> tuple[bool, float]:
    headline = result.headline_rho
    return (headline is None, 0.0 if headline is None else -abs(headline))


def _controls_array(controls: pd.DataFrame, length: int) -> np.ndarray:
    out = np.column_stack([_numeric(controls[column]) for column in controls.columns])
    if len(out) != length:
        raise ValueError("controls must have the same length as x and y")
    return out


def _as_float(values: pd.Series | np.ndarray) -> np.ndarray:
    if isinstance(values, pd.Series):
        return _numeric(values)
    return np.asarray(values, dtype="float64")
