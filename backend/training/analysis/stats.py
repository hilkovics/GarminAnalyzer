"""Vectorized statistics helpers for the sleep ↔ performance correlation – METRICS §9.

Every `*_rows` function works on a batch of samples laid out as rows: shape `(B, n)` (or `(B, n, k)` for
the controls), where row `b` is one bootstrap resample (or `B = 1` for the point estimate). The building
blocks (`centered_ranks`, `ols_projector`, `quartile_groups`) are split out so a caller can reuse the part
that depends on one variable only across many pairs. Pure numpy / scipy, no I/O.
"""

import warnings
from collections import OrderedDict
from collections.abc import Callable, Hashable
from dataclasses import dataclass

import numpy as np
from scipy import stats

# METRICS §9 (clarified): quartile contrast "needs ≥ 5 rows in each group, else null".
MIN_GROUP_ROWS = 5
# METRICS §9 (clarified): "if more than 10 % [of the resamples] are NaN, the CI is null".
MAX_NAN_FRACTION = 0.10
# METRICS §9 (clarified): "the CI is the percentile interval (2.5 %, 97.5 %)".
CI_PERCENTILES = (2.5, 97.5)

# Residuals whose largest magnitude is below this fraction of the input's are numerically zero: the variable
# is fully explained by the controls (e.g. constant), so its partial correlation is undefined (NaN).
_RESIDUAL_RTOL = 1e-9
# Cut-off for the pseudo-inverse of the (k+1)×(k+1) Gram matrix (singular designs, e.g. a constant control).
_PINV_RCOND = 1e-10


class Memo:
    """Small LRU memo, `maxsize` most recently used entries per family.

    Only a speed-up: the correlation of many (predictor, outcome) pairs reuses the resample matrices, the
    per-variable ranks and the OLS projector that depend on one side (and the row set) only. Results are
    identical with or without it.
    """

    def __init__(self, maxsize: int = 4) -> None:
        self._maxsize = maxsize
        self._families: dict[str, OrderedDict[Hashable, object]] = {}

    def get[T](self, family: str, key: Hashable, compute: Callable[[], T]) -> T:
        cache = self._families.setdefault(family, OrderedDict())
        if key in cache:
            cache.move_to_end(key)
            return cache[key]  # type: ignore[return-value]
        value = compute()
        cache[key] = value
        if len(cache) > self._maxsize:
            cache.popitem(last=False)
        return value


def resample_indices(n: int, n_boot: int, seed: int) -> np.ndarray:
    """`(n_boot, n)` bootstrap row indices (with replacement) from `numpy.random.default_rng(seed)` – §9."""
    return np.random.default_rng(seed).integers(0, n, size=(n_boot, n))


def spearman(x: np.ndarray, y: np.ndarray) -> tuple[float | None, float | None]:
    """Spearman ρ and its p-value (t approximation) via `scipy.stats.spearmanr` – METRICS §9.

    Returns `(None, None)` when either input is constant (ρ undefined), without emitting scipy's warning.
    """
    if len(x) < 2 or np.ptp(x) == 0 or np.ptp(y) == 0:
        return None, None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", stats.ConstantInputWarning)
        result = stats.spearmanr(x, y)
    rho, p = float(result.statistic), float(result.pvalue)
    if not np.isfinite(rho):
        return None, None
    return rho, (p if np.isfinite(p) else None)


# --------------------------------------------------------------------------------------------------
# row-wise Spearman


@dataclass(frozen=True)
class CenteredRanks:
    """Row-centred average ranks of a `(B, n)` array and their row sums of squares."""

    ranks: np.ndarray
    sum_sq: np.ndarray


def centered_ranks(a: np.ndarray) -> CenteredRanks:
    """Average ranks along axis 1 (`scipy.stats.rankdata`, ties averaged), centred per row."""
    ranks = stats.rankdata(a, axis=1)
    ranks -= ranks.mean(axis=1, keepdims=True)
    return CenteredRanks(ranks, np.einsum("ij,ij->i", ranks, ranks))


def pearson_of_ranks(a: CenteredRanks, b: CenteredRanks) -> np.ndarray:
    """Row-wise Pearson of two centred rank arrays = Spearman ρ per row; NaN where a row is constant."""
    num = np.einsum("ij,ij->i", a.ranks, b.ranks)
    den = np.sqrt(a.sum_sq * b.sum_sq)
    ok = den > 0
    rho = np.full(num.shape, np.nan)
    rho[ok] = num[ok] / den[ok]
    return np.clip(rho, -1.0, 1.0)


def spearman_rows(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Row-wise Spearman ρ of two `(B, n)` arrays (average ranks for ties) – METRICS §9.

    Equals `scipy.stats.spearmanr(a[i], b[i]).statistic` for every row `i`; a row where either side is
    constant gives NaN.
    """
    return pearson_of_ranks(centered_ranks(a), centered_ranks(b))


# --------------------------------------------------------------------------------------------------
# batched OLS residualization (partial correlation)


@dataclass(frozen=True)
class OlsProjector:
    """Per-row design `Z = [1, controls]` and `pinv(ZᵀZ)`, so `β = pinv(ZᵀZ) · Zᵀv` for any response `v`."""

    design: np.ndarray  # (B, n, k + 1)
    gram_pinv: np.ndarray  # (B, k + 1, k + 1)


def ols_projector(controls: np.ndarray) -> OlsProjector:
    """Batched least-squares projector for an intercept plus `controls` of shape `(B, n, k)` – METRICS §9.

    Closed form `β = pinv(ZᵀZ) · Zᵀv` per row; the pseudo-inverse gives the least-squares solution also for a
    rank-deficient resample (e.g. a control that is constant in it). The controls are standardized first:
    with an intercept in the design that affine change leaves the residuals unchanged but conditions the
    Gram matrix far better.
    """
    batch, n, k = controls.shape
    flat = controls.reshape(-1, k)
    scale = flat.std(axis=0)
    scale[scale == 0] = 1.0
    design = np.empty((batch, n, k + 1))
    design[..., 0] = 1.0
    design[..., 1:] = (controls - flat.mean(axis=0)) / scale
    gram = design.transpose(0, 2, 1) @ design
    return OlsProjector(design, np.linalg.pinv(gram, rcond=_PINV_RCOND, hermitian=True))


def ols_residuals(projector: OlsProjector, v: np.ndarray) -> np.ndarray:
    """Residuals `v − Z β` per row of `v` `(B, n)`; numerically-zero residual rows are set to exactly 0.

    Zeroing them makes the Spearman ρ of a variable that the controls fully explain NaN, rather than a
    correlation of rounding noise.
    """
    moment = np.einsum("bni,bn->bi", projector.design, v)
    beta = np.einsum("bij,bj->bi", projector.gram_pinv, moment)
    resid = v - np.einsum("bni,bi->bn", projector.design, beta)
    negligible = np.max(np.abs(resid), axis=1) <= _RESIDUAL_RTOL * np.max(np.abs(v), axis=1)
    resid[negligible] = 0.0
    return resid


def residualize_rows(x: np.ndarray, y: np.ndarray, controls: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """OLS residuals of `x` and `y` `(B, n)` on an intercept plus `controls` `(B, n, k)`, per row – §9."""
    projector = ols_projector(controls)
    return ols_residuals(projector, x), ols_residuals(projector, y)


# --------------------------------------------------------------------------------------------------
# quartile contrast


@dataclass(frozen=True)
class QuartileGroups:
    """Per-row bottom (`x ≤ Q1`) and top (`x ≥ Q3`) membership of a `(B, n)` predictor array."""

    bottom: np.ndarray  # bool (B, n)
    top: np.ndarray  # bool (B, n)
    n_bottom: np.ndarray  # int (B,)
    n_top: np.ndarray  # int (B,)


def quartile_groups(x: np.ndarray) -> QuartileGroups:
    """`Q1`/`Q3` as numpy linear quantiles of each row; `bottom = x ≤ Q1`, `top = x ≥ Q3` – METRICS §9."""
    q1, q3 = np.quantile(x, [0.25, 0.75], axis=1)
    bottom = x <= q1[:, None]
    top = x >= q3[:, None]
    return QuartileGroups(bottom, top, bottom.sum(axis=1), top.sum(axis=1))


def quartile_contrast(groups: QuartileGroups, y: np.ndarray) -> np.ndarray:
    """`mean(y | top) − mean(y | bottom)` per row; NaN where a group has < `MIN_GROUP_ROWS` rows."""
    enough = (groups.n_bottom >= MIN_GROUP_ROWS) & (groups.n_top >= MIN_GROUP_ROWS)
    contrast = np.full(y.shape[0], np.nan)
    if enough.any():
        top_mean = np.einsum("ij,ij->i", groups.top[enough], y[enough]) / groups.n_top[enough]
        bottom_mean = np.einsum("ij,ij->i", groups.bottom[enough], y[enough]) / groups.n_bottom[enough]
        contrast[enough] = top_mean - bottom_mean
    return contrast


def quartile_contrast_rows(x: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Row-wise quartile contrast of `y` on `x` – METRICS §9. Returns `(contrast, n_bottom, n_top)`."""
    groups = quartile_groups(x)
    return quartile_contrast(groups, y), groups.n_bottom, groups.n_top


# --------------------------------------------------------------------------------------------------
# confidence interval


def percentile_ci(values: np.ndarray) -> tuple[float | None, float | None]:
    """Bootstrap percentile CI (2.5 %, 97.5 %) over the non-NaN resamples – METRICS §9 (clarified).

    NaN resamples (a constant column) are dropped; if more than 10 % are NaN the CI is null.
    """
    if values.size == 0:
        return None, None
    valid = values[~np.isnan(values)]
    if valid.size == 0 or (values.size - valid.size) > MAX_NAN_FRACTION * values.size:
        return None, None
    low, high = np.percentile(valid, CI_PERCENTILES)
    return float(low), float(high)


def is_uncertain(rho: float | None, ci_low: float | None, ci_high: float | None) -> bool:
    """METRICS §9: a finding whose CI contains 0 (or whose ρ / CI is null) is labelled uncertain."""
    if rho is None or ci_low is None or ci_high is None:
        return True
    return ci_low <= 0.0 <= ci_high


def finite_or_none(value: float) -> float | None:
    """`float(value)`, or `None` for NaN / ±inf (null statistic)."""
    return float(value) if np.isfinite(value) else None
