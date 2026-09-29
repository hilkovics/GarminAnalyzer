"""Wellness, readiness and correlation services (phase 5, METRICS §8–§9).

Loads the frames of `training.pipeline_wellness`, hands them to the pure functions of `training.analysis`
and assembles DTOs – no formula lives here. Units are internal (seconds, bpm, points); h:mm is a
presentation matter.

`get_correlations` bootstraps (3–30 s on real data), so its per-sport result is kept in a small in-process
cache keyed by a hash of all its input frames (so any data change refreshes it).
"""

import datetime as dt
import hashlib
import logging
import math
import threading
from collections import OrderedDict
from typing import Any

import pandas as pd
from sqlmodel import Session

from training.analysis.correlation import MIN_N, N_BOOT, SPORTS, build_dataset, correlations
from training.analysis.readiness import ReadinessResult, band, readiness
from training.analysis.wellness import BASELINE_FIELDS, with_baselines
from training.pipeline_wellness import correlation_activities, daily_frame, wellness_frame
from training.services.dto import (
    BaselineDTO,
    CorrelationDTO,
    CorrelationsDTO,
    ReadinessComponentDTO,
    ReadinessDTO,
    WellnessBaselinesDTO,
    WellnessDayDTO,
    WellnessDTO,
)
from training.services.errors import InvalidInputError
from training.services.sleep_findings import CAVEAT, correlation_dto

log = logging.getLogger(__name__)

__all__ = ["CAVEAT", "clear_cache", "get_correlations", "get_readiness", "get_wellness"]

MAX_DAYS = 3650
CACHE_SIZE = 16
BAND_MESSAGES = {
    "green": "Trénuj podľa plánu, môžeš pridať.",
    "yellow": "Podľa plánu, nič navyše.",
    "red": "Ľahko alebo voľno.",
}
NO_SCORE_MESSAGE = "Na tento deň nie je dosť wellness dát na výpočet pripravenosti."
COMPONENT_ORDER = ("rhr", "sleep", "body_battery", "form")


def _num(value: Any) -> float | None:
    """None for None / NaN / NA, else a float."""
    if value is None or value is pd.NA:
        return None
    number = float(value)
    return None if math.isnan(number) else number


def _time(value: Any) -> dt.datetime | None:
    return None if value is None or pd.isna(value) else pd.Timestamp(value).to_pydatetime()


# --- wellness ---------------------------------------------------------------------------------------------


def _baseline(row: pd.Series, field: str) -> BaselineDTO:
    return BaselineDTO(median=_num(row[f"{field}_median28"]), mad=_num(row[f"{field}_mad28"]))


def _day_dto(day: dt.date, row: pd.Series, persisted: float | None) -> WellnessDayDTO:
    steps = _num(row["steps"])
    return WellnessDayDTO(
        date=day,
        sleep_start=_time(row["sleep_start"]),
        sleep_end=_time(row["sleep_end"]),
        sleep_s=_num(row["sleep_s"]),
        deep_s=_num(row["deep_s"]),
        light_s=_num(row["light_s"]),
        rem_s=_num(row["rem_s"]),
        awake_s=_num(row["awake_s"]),
        sleep_score=_num(row["sleep_score"]),
        rhr=_num(row["rhr"]),
        body_battery_wake=_num(row["body_battery_wake"]),
        body_battery_min=_num(row["body_battery_min"]),
        stress_avg=_num(row["stress_avg"]),
        steps=None if steps is None else int(steps),
        weight_kg=_num(row["weight_kg"]),
        baselines=WellnessBaselinesDTO(**{f: _baseline(row, f) for f in BASELINE_FIELDS}),
        sleep_debt_7_s=_num(row["sleep_debt_7"]),
        readiness=persisted,
        readiness_band=band(persisted),
    )


def get_wellness(
    session: Session, date_from: dt.date | None = None, date_to: dt.date | None = None
) -> WellnessDTO:
    """Wellness rows in [date_from, date_to] with their §8 baselines, sleep debt and persisted readiness.

    Baselines and sleep debt are computed over the whole stored history and then sliced to the range, so
    the first days of a range still have a baseline.
    """
    if date_from is not None and date_to is not None and date_from > date_to:
        raise InvalidInputError("from must not be after to")
    if date_from is not None and date_to is not None and (date_to - date_from).days + 1 > MAX_DAYS:
        raise InvalidInputError(f"the range must not exceed {MAX_DAYS} days")
    frame = with_baselines(wellness_frame(session))
    readiness_by_day = daily_frame(session)["readiness"]
    days = []
    for day, row in frame.iterrows():
        if (date_from is not None and day < date_from) or (date_to is not None and day > date_to):
            continue
        persisted = _num(readiness_by_day.get(day))
        days.append(_day_dto(day, row, persisted))
    return WellnessDTO(
        days=days,
        date_from=date_from or (days[0].date if days else None),
        date_to=date_to or (days[-1].date if days else None),
    )


# --- readiness --------------------------------------------------------------------------------------------


def _components(
    result: ReadinessResult, row: pd.Series | None, tsb: float | None
) -> list[ReadinessComponentDTO]:
    """Score, weight and the raw input / baseline of each component, in table order."""

    def get(key: str) -> float | None:
        return _num(row[key]) if row is not None else None

    sleep_score = get("sleep_score")
    sleep_input = (
        (sleep_score, get("sleep_score_median28"), "score")
        if sleep_score is not None
        else (get("sleep_s"), get("sleep_s_median28"), "s")
    )
    inputs = {
        "rhr": (get("rhr"), get("rhr_median28"), "bpm"),
        "sleep": sleep_input,
        "body_battery": (get("body_battery_wake"), get("body_battery_wake_median28"), "points"),
        "form": (tsb, None, "TSB"),
    }
    return [
        ReadinessComponentDTO(
            name=name,
            score=result.components.get(name),
            weight=result.weights.get(name),
            value=inputs[name][0],
            baseline=inputs[name][1],
            unit=inputs[name][2],
        )
        for name in COMPONENT_ORDER
    ]


def get_readiness(session: Session, day: dt.date) -> ReadinessDTO:
    """Readiness of `day` (METRICS §8), recomputed from that day's wellness row, baselines and TSB.

    Uses the same `readiness()` as the pipeline, so the score equals the persisted `daily_load.readiness`.
    A day without a wellness row (or with no wellness component) is `available = False`.
    """
    frame = with_baselines(wellness_frame(session))
    row = frame.loc[day] if day in frame.index else None
    tsb = _num(daily_frame(session)["tsb"].get(day))
    if row is None:
        result = readiness(
            rhr=None,
            rhr_median28=None,
            sleep_score=None,
            sleep_s=None,
            sleep_s_median28=None,
            body_battery_wake=None,
            tsb=tsb,
        )
    else:
        result = readiness(
            rhr=_num(row["rhr"]),
            rhr_median28=_num(row["rhr_median28"]),
            sleep_score=_num(row["sleep_score"]),
            sleep_s=_num(row["sleep_s"]),
            sleep_s_median28=_num(row["sleep_s_median28"]),
            body_battery_wake=_num(row["body_battery_wake"]),
            tsb=tsb,
        )
    available = result.score is not None
    return ReadinessDTO(
        date=day,
        available=available,
        score=result.score,
        band=result.band,
        components=_components(result, row, tsb),
        message=BAND_MESSAGES[result.band] if result.band else NO_SCORE_MESSAGE,
    )


# --- correlations -----------------------------------------------------------------------------------------

_cache: OrderedDict[tuple, tuple[list[CorrelationDTO], int]] = OrderedDict()
_cache_lock = threading.Lock()


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _frames(session: Session) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """The exact §9 inputs: activities with outcomes, wellness with baselines, daily load (all small)."""
    return correlation_activities(session), with_baselines(wellness_frame(session)), daily_frame(session)


def _fingerprint(*frames: pd.DataFrame) -> str:
    """Hash of every value the correlation reads (review phase 5, blocker 1): any changed input – a revised
    RHR, a recomputed decoupling, a new TSB – changes the key, so cached findings are never stale."""
    digest = hashlib.sha256()
    for frame in frames:
        digest.update(",".join(map(str, frame.columns)).encode())
        digest.update(pd.util.hash_pandas_object(frame.astype(object), index=True).to_numpy().tobytes())
    return digest.hexdigest()


def _cached_sport(
    frames: tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame], digest: str, sport: str, n_boot: int
) -> tuple[list[CorrelationDTO], int]:
    """Results of one sport (sorted by |headline ρ|) and its qualifying days, cached by input hash."""
    activities, wellness, daily = frames
    key = (digest, sport, n_boot)
    with _cache_lock:
        if key in _cache:
            _cache.move_to_end(key)
            return _cache[key]
    dataset = build_dataset(activities, wellness, daily, sport)
    value = [correlation_dto(r) for r in correlations(dataset, sport, n_boot=n_boot)], len(dataset)
    with _cache_lock:
        _cache[key] = value
        while len(_cache) > CACHE_SIZE:
            _cache.popitem(last=False)
    return value


def _sort_key(dto: CorrelationDTO) -> tuple[bool, float]:
    return (dto.headline_rho is None, 0.0 if dto.headline_rho is None else -abs(dto.headline_rho))


def get_correlations(session: Session, sport: str | None = None, n_boot: int = N_BOOT) -> CorrelationsDTO:
    """Sleep ↔ performance findings (METRICS §9) for one sport or for run and bike.

    `findings` (n ≥ 30) are sorted by |headline ρ| across the sports; `insufficient` lists the other pairs
    with their n. The bootstrap is cached per (hash of all inputs, sport, n_boot).
    """
    if sport is not None and sport not in SPORTS:
        raise InvalidInputError(f"sport must be one of {', '.join(SPORTS)}")
    if not 1 <= n_boot <= 100_000:
        raise InvalidInputError("n_boot must be between 1 and 100000")
    sports = [sport] if sport else list(SPORTS)
    results: list[CorrelationDTO] = []
    n_days: dict[str, int] = {}
    frames = _frames(session)  # loaded and hashed once for both sports
    digest = _fingerprint(*frames)
    for name in sports:
        found, n_days[name] = _cached_sport(frames, digest, name, n_boot)
        results += found
    return CorrelationsDTO(
        sports=sports,
        findings=sorted((r for r in results if r.status == "ok"), key=_sort_key),
        insufficient=[r for r in results if r.status != "ok"],
        min_n=MIN_N,
        caveat=CAVEAT,
        n_days=n_days,
    )
