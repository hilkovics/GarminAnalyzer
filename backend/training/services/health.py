"""Health page (METRICS §12): glue only – `training.analysis.health` computes, this module assembles DTOs."""

import datetime as dt
import math

import pandas as pd
from sqlmodel import Session

from training.analysis import health as h
from training.pipeline_wellness import health_frame
from training.services.dto import (
    HealthMetricDTO,
    HealthOverviewDTO,
    HealthPointDTO,
    HealthRelationshipDTO,
    HealthRelationshipsDTO,
    HealthSeriesDTO,
    MonthValueDTO,
    RecentChangeDTO,
)
from training.services.errors import InvalidInputError

MAX_DAYS = 3650
HISTORY_GAP_D = 28  # §12.1: a metric starting later than this after the first health day is "history missing"
MAX_SERIES = 4
MAX_OTHERS = 20
WEAK_BELOW, MEDIUM_BELOW = 0.3, 0.5


def _num(value: object) -> float | None:
    if value is None:
        return None
    number = float(value)  # type: ignore[arg-type]
    return number if math.isfinite(number) else None


def _first_date(frame: pd.DataFrame) -> dt.date | None:
    present = frame.dropna(how="all")
    return present.index[0] if len(present) else None


def get_overview(session: Session, today: dt.date) -> HealthOverviewDTO:
    frame = health_frame(session, today)
    metrics = []
    for info in h.METRICS:
        series = frame[info.key] if info.key in frame else pd.Series(dtype=float)
        t = h.trends(series) if len(series) else None
        last = series.dropna()
        row = t.iloc[-1] if t is not None and len(t) else None
        change = h.recent_change(series, today, info.better)
        metrics.append(
            HealthMetricDTO(
                key=info.key,
                label=info.label,
                unit=info.unit,
                better=info.better,
                latest=_num(last.iloc[-1]) if len(last) else None,
                latest_date=last.index[-1] if len(last) else None,
                history_from=last.index[0] if len(last) else None,
                mean7=_num(row["mean7"]) if row is not None else None,
                mean28=_num(row["mean28"]) if row is not None else None,
                median28=_num(row["median28"]) if row is not None else None,
                mad28=_num(row["mad28"]) if row is not None else None,
                change=RecentChangeDTO(**change.__dict__),
                monthly=[MonthValueDTO(month=m, value=float(v)) for m, v in h.monthly(series).items()],
            )
        )
    first = _first_date(frame)
    missing = [
        m.key
        for m in metrics
        if first is not None and m.history_from is not None and (m.history_from - first).days > HISTORY_GAP_D
    ]
    return HealthOverviewDTO(today=today, first_date=first, metrics=metrics, missing_history=missing)


def get_series(session: Session, keys: list[str], *, days: int, today: dt.date) -> list[HealthSeriesDTO]:
    """Daily value, 7-day mean and the normal band of up to 4 metrics for the last `days` days."""
    unknown = [k for k in keys if k not in h.BY_KEY]
    if unknown:
        raise InvalidInputError(f"unknown metric(s): {', '.join(unknown)}")
    if not 1 <= len(keys) <= MAX_SERIES:
        raise InvalidInputError(f"choose 1 to {MAX_SERIES} metrics")
    if not 7 <= days <= MAX_DAYS:
        raise InvalidInputError(f"days must be between 7 and {MAX_DAYS}")
    frame = health_frame(session, today)
    start = today - dt.timedelta(days=days - 1)
    out = []
    for key in keys:
        info = h.BY_KEY[key]
        t = (
            h.trends(frame[key])
            if len(frame)
            else pd.DataFrame(columns=["value", "mean7", "median28", "mad28", "pct"])
        )
        t = t[[d >= start for d in t.index]] if len(t) else t
        points = [
            HealthPointDTO(
                date=d,
                value=_num(r["value"]),
                mean7=_num(r["mean7"]),
                median28=_num(r["median28"]),
                mad28=_num(r["mad28"]),
                pct=_num(r["pct"]),
            )
            for d, r in t.iterrows()
        ]
        out.append(
            HealthSeriesDTO(key=key, label=info.label, unit=info.unit, better=info.better, points=points)
        )
    return out


def _strength(rho: float) -> str:
    size = abs(rho)
    return "slabá" if size < WEAK_BELOW else "stredná" if size < MEDIUM_BELOW else "silná"


def sentence(r: h.Relationship) -> str:
    """Plain Slovak sentence of one §12.3 relationship."""
    x, y = h.BY_KEY[r.x].label, h.BY_KEY[r.y].label
    when = "v nasledujúci deň" if r.lag else "v ten istý deň"
    side = "nad" if (r.rho or 0) > 0 else "pod"
    rho = f"{r.rho or 0:.2f}".replace(".", ",").replace("-", "−")
    return (
        f"Keď je „{x}“ nad tvojím normálom, „{y}“ býva {when} skôr {side} normálom – "
        f"{_strength(r.rho or 0)} súvislosť (ρ = {rho}, n = {r.n})."
    )


def _dto(r: h.Relationship) -> HealthRelationshipDTO:
    assert r.rho is not None and r.ci_low is not None and r.ci_high is not None and r.p is not None
    return HealthRelationshipDTO(
        x=r.x,
        y=r.y,
        lag=r.lag,
        n=r.n,
        rho=r.rho,
        ci_low=r.ci_low,
        ci_high=r.ci_high,
        p=r.p,
        finding=r.finding,
        contrast=r.contrast,
        text=sentence(r),
    )


def get_relationships(session: Session, today: dt.date) -> HealthRelationshipsDTO:
    results = h.relationships(health_frame(session, today))
    findings = [_dto(r) for r in results if r.finding]
    others = [_dto(r) for r in results if not r.finding][:MAX_OTHERS]
    return HealthRelationshipsDTO(tested=len(results), findings=findings, others=others)
