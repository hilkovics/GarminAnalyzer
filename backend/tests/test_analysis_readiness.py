"""Readiness score 0–100 (METRICS §8, phase 5 clarifications).

Every expected value is hand-computed in the comments. Tolerance 1e-9 throughout.
"""

import dataclasses
import math
from datetime import date, timedelta
from typing import Any

import numpy as np
import pandas as pd
import pytest

from training.analysis.readiness import (
    WEIGHTS,
    ReadinessResult,
    band,
    readiness,
    readiness_frame,
)
from training.analysis.wellness import with_baselines

TOL = 1e-9
H = 3600.0
D0 = date(2026, 3, 2)
NONE: dict[str, float | None] = {
    "rhr": None,
    "rhr_median28": None,
    "sleep_score": None,
    "sleep_s": None,
    "sleep_s_median28": None,
    "body_battery_wake": None,
    "tsb": None,
}


def ready(**kwargs: Any) -> ReadinessResult:
    return readiness(**{**NONE, **kwargs})


# ---------------------------------------------------------------------------------------------------------
# constants, bands


def test_weights() -> None:
    assert WEIGHTS == {"rhr": 0.30, "sleep": 0.30, "body_battery": 0.20, "form": 0.20}


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (100.0, "green"),
        (70.0, "green"),
        (69.999999, "yellow"),
        (45.0, "yellow"),
        (44.999999, "red"),
        (0.0, "red"),
        (None, None),
        (float("nan"), None),
    ],
)
def test_band_edges(score: float | None, expected: str | None) -> None:
    assert band(score) == expected


def test_result_is_frozen() -> None:
    result = ready(sleep_score=80.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        result.score = 1.0  # type: ignore[misc]


# ---------------------------------------------------------------------------------------------------------
# readiness – all components


def test_all_components_hand_computed() -> None:
    # RHR 52 vs median 50 → 100 − 12.5 · 2 = 75; sleep_score 80; BB 60; TSB −5 → 50 − 10 = 40.
    # 0.3 · 75 + 0.3 · 80 + 0.2 · 60 + 0.2 · 40 = 22.5 + 24 + 12 + 8 = 66.5 → yellow.
    r = ready(rhr=52.0, rhr_median28=50.0, sleep_score=80.0, sleep_s=4 * H, body_battery_wake=60.0, tsb=-5.0)
    assert r.score == pytest.approx(66.5, abs=TOL)
    assert r.band == "yellow"
    assert r.components == pytest.approx({"rhr": 75.0, "sleep": 80.0, "body_battery": 60.0, "form": 40.0})
    assert r.weights == pytest.approx(WEIGHTS)


def test_unrounded_score_drives_band() -> None:
    # RHR 49.6 vs 50 → 100; sleep 66.6; BB 50; TSB 0 → 50: 30 + 19.98 + 10 + 10 = 69.98 → yellow
    # (it would display as 70, but the band uses the unrounded value).
    r = ready(rhr=49.6, rhr_median28=50.0, sleep_score=66.6, body_battery_wake=50.0, tsb=0.0)
    assert r.score == pytest.approx(69.98, abs=TOL)
    assert r.band == "yellow"


# ---------------------------------------------------------------------------------------------------------
# missing components and renormalization


def test_rhr_missing_renormalizes_exactly() -> None:
    # Sleep 80, BB 60, Form 40 with weights 0.3/0.7, 0.2/0.7, 0.2/0.7 → (24 + 12 + 8) / 0.7 = 440/7.
    r = ready(sleep_score=80.0, body_battery_wake=60.0, tsb=-5.0)
    assert r.score == pytest.approx(440 / 7, abs=TOL)
    assert r.components["rhr"] is None
    assert set(r.weights) == {"sleep", "body_battery", "form"}
    assert r.weights["sleep"] == pytest.approx(3 / 7, abs=TOL)
    assert r.weights["body_battery"] == pytest.approx(2 / 7, abs=TOL)
    assert r.weights["form"] == pytest.approx(2 / 7, abs=TOL)
    assert sum(r.weights.values()) == pytest.approx(1.0, abs=TOL)


def test_rhr_null_when_median_null() -> None:
    r = ready(rhr=50.0, rhr_median28=None, sleep_score=80.0)
    assert r.components["rhr"] is None
    assert r.score == pytest.approx(80.0, abs=TOL)
    assert r.weights == pytest.approx({"sleep": 1.0})


def test_nan_counts_as_none() -> None:
    nan = float("nan")
    r = readiness(
        rhr=nan,
        rhr_median28=50.0,
        sleep_score=nan,
        sleep_s=nan,
        sleep_s_median28=nan,
        body_battery_wake=70.0,
        tsb=nan,
    )
    assert r.components == {"rhr": None, "sleep": None, "body_battery": 70.0, "form": None}
    assert r.score == pytest.approx(70.0, abs=TOL)
    assert r.band == "green"
    assert r.weights == pytest.approx({"body_battery": 1.0})


def test_only_tsb_gives_none() -> None:
    r = ready(tsb=10.0)
    assert r.score is None
    assert r.band is None
    assert r.components == {"rhr": None, "sleep": None, "body_battery": None, "form": 70.0}
    assert r.weights == {}


def test_nothing_gives_none() -> None:
    r = ready()
    assert r.score is None
    assert r.band is None
    assert set(r.components) == {"rhr", "sleep", "body_battery", "form"}
    assert all(v is None for v in r.components.values())


def test_rhr_and_body_battery_without_form() -> None:
    # RHR 100 (below median), BB 30: (0.3 · 100 + 0.2 · 30) / 0.5 = 36 / 0.5 = 72.
    r = ready(rhr=45.0, rhr_median28=50.0, body_battery_wake=30.0)
    assert r.score == pytest.approx(72.0, abs=TOL)
    assert r.weights == pytest.approx({"rhr": 0.6, "body_battery": 0.4})


# ---------------------------------------------------------------------------------------------------------
# clamps


@pytest.mark.parametrize(
    ("tsb", "expected"),
    [(80.0, 100.0), (25.0, 100.0), (0.0, 50.0), (-25.0, 0.0), (-60.0, 0.0), (10.5, 71.0)],
)
def test_form_clamped(tsb: float, expected: float) -> None:
    # 50 + 2 · 80 = 210 → 100; 50 − 120 = −70 → 0.
    r = ready(tsb=tsb, body_battery_wake=50.0)
    assert r.components["form"] == pytest.approx(expected, abs=TOL)


@pytest.mark.parametrize(
    ("rhr", "expected"),
    [
        (40.0, 100.0),  # below median → max(0, ·) = 0 → 100
        (50.0, 100.0),
        (51.0, 87.5),
        (54.0, 50.0),
        (58.0, 0.0),  # 100 − 12.5 · 8 = 0
        (60.0, 0.0),  # 100 − 125 = −25 → 0
    ],
)
def test_rhr_score_clamped(rhr: float, expected: float) -> None:
    r = ready(rhr=rhr, rhr_median28=50.0)
    assert r.components["rhr"] == pytest.approx(expected, abs=TOL)
    assert r.score == pytest.approx(expected, abs=TOL)


def test_body_battery_and_sleep_score_clamped() -> None:
    r = ready(sleep_score=120.0, body_battery_wake=-5.0)
    assert r.components["sleep"] == pytest.approx(100.0, abs=TOL)
    assert r.components["body_battery"] == pytest.approx(0.0, abs=TOL)


# ---------------------------------------------------------------------------------------------------------
# sleep fallback


def test_sleep_score_preferred_over_fallback() -> None:
    r = ready(sleep_score=55.0, sleep_s=8 * H, sleep_s_median28=8 * H)
    assert r.components["sleep"] == pytest.approx(55.0, abs=TOL)


def test_sleep_score_zero_is_present() -> None:
    r = ready(sleep_score=0.0, sleep_s=8 * H)
    assert r.components["sleep"] == pytest.approx(0.0, abs=TOL)


@pytest.mark.parametrize(
    ("sleep_s", "median", "expected"),
    [
        (6 * H, None, 80.0),  # null median counts as 7.5 h: 100 · 6 / 7.5 = 80
        (6 * H, float("nan"), 80.0),
        (6 * H, 7 * H, 80.0),  # max(7.5 h, 7 h) = 7.5 h
        (6 * H, 8 * H, 75.0),  # 100 · 6 / 8
        (9 * H, None, 100.0),  # 120 → clamped
        (0.0, None, 0.0),
    ],
)
def test_sleep_fallback(sleep_s: float, median: float | None, expected: float) -> None:
    r = ready(sleep_s=sleep_s, sleep_s_median28=median)
    assert r.components["sleep"] == pytest.approx(expected, abs=TOL)
    assert r.score == pytest.approx(expected, abs=TOL)


# ---------------------------------------------------------------------------------------------------------
# readiness_frame


def wellness_rows(rows: dict[int, dict[str, float | None]]) -> pd.DataFrame:
    index = pd.Index([D0 + timedelta(days=d) for d in rows], name="date")
    cols = ("rhr", "rhr_median28", "sleep_score", "sleep_s", "sleep_s_median28", "body_battery_wake")
    data = {c: [np.nan if r.get(c) is None else r[c] for r in rows.values()] for c in cols}
    return pd.DataFrame(data, index=index, dtype=float)


def test_readiness_frame_rows_and_columns() -> None:
    wellness = wellness_rows(
        {
            0: {"rhr": 52.0, "rhr_median28": 50.0, "sleep_score": 80.0, "body_battery_wake": 60.0},
            1: {"sleep_score": 80.0, "body_battery_wake": 60.0},
            3: {},  # nothing but TSB → no score
            4: {"sleep_s": 6 * H},  # TSB missing for this date → Form missing
        }
    )
    # TSB on a DatetimeIndex (as §4 pmc may return), with an extra date that has no wellness row.
    tsb = pd.Series(
        [-5.0, -5.0, 3.0, 10.0],
        index=pd.DatetimeIndex([pd.Timestamp(D0 + timedelta(days=d)) for d in (0, 1, 2, 3)], name="date"),
    )
    out = readiness_frame(wellness, tsb)
    assert list(out.index) == list(wellness.index)
    assert list(out.columns) == [
        "readiness",
        "band",
        "rhr_score",
        "sleep_score_c",
        "body_battery_score",
        "form_score",
    ]
    r = out.to_dict(orient="index")
    d = [D0 + timedelta(days=i) for i in range(5)]
    assert r[d[0]]["readiness"] == pytest.approx(66.5, abs=TOL)
    assert r[d[0]]["band"] == "yellow"
    assert r[d[0]]["rhr_score"] == pytest.approx(75.0, abs=TOL)
    assert r[d[1]]["readiness"] == pytest.approx(440 / 7, abs=TOL)
    assert math.isnan(r[d[1]]["rhr_score"])
    assert math.isnan(r[d[3]]["readiness"])
    assert r[d[3]]["band"] is None
    assert r[d[3]]["form_score"] == pytest.approx(70.0, abs=TOL)
    assert r[d[4]]["readiness"] == pytest.approx(80.0, abs=TOL)
    assert r[d[4]]["sleep_score_c"] == pytest.approx(80.0, abs=TOL)
    assert math.isnan(r[d[4]]["form_score"])
    assert r[d[4]]["band"] == "green"


def test_readiness_frame_missing_columns_and_empty_tsb() -> None:
    wellness = pd.DataFrame(
        {"body_battery_wake": [40.0, np.nan]},
        index=pd.Index([D0, D0 + timedelta(days=1)], name="date"),
    )
    out = readiness_frame(wellness, pd.Series(dtype=float))
    assert out["readiness"].iloc[0] == pytest.approx(40.0, abs=TOL)
    assert out["band"].iloc[0] == "red"
    assert math.isnan(out["readiness"].iloc[1])
    assert out["band"].iloc[1] is None
    assert out["form_score"].isna().all()


def test_readiness_frame_on_with_baselines_output() -> None:
    # 29 days: rhr 50, sleep_score 75, BB 80 on days 0..27; day 28 rhr 54 → RHR score 50.
    # TSB 0 → Form 50. Day 28: 0.3 · 50 + 0.3 · 75 + 0.2 · 80 + 0.2 · 50 = 15 + 22.5 + 16 + 10 = 63.5.
    n = 29
    index = pd.Index([D0 + timedelta(days=i) for i in range(n)], name="date")
    wellness = pd.DataFrame(
        {"rhr": [50.0] * 28 + [54.0], "sleep_score": [75.0] * n, "body_battery_wake": [80.0] * n},
        index=index,
    )
    tsb = pd.Series([0.0] * n, index=index)
    out = readiness_frame(with_baselines(wellness), tsb)
    assert out["readiness"].iloc[28] == pytest.approx(63.5, abs=TOL)
    # Day 0: no RHR baseline yet → (0.3 · 75 + 0.2 · 80 + 0.2 · 50) / 0.7 = 48.5 / 0.7.
    assert out["readiness"].iloc[0] == pytest.approx(48.5 / 0.7, abs=TOL)
    assert math.isnan(out["rhr_score"].iloc[6])
    assert out["rhr_score"].iloc[7] == pytest.approx(100.0, abs=TOL)
