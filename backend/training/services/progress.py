"""EF, speed–HR curve, best efforts, predictions, proposals (phase 4, METRICS §5–§7).

Reads what the pipeline stored (`activity_metric`, `best_effort`, `curve_snapshot`, `raw_garmin`) and hands it
to the pure functions of `training.metrics` – no formula lives here. Everything returns DTOs in internal units
(m/s, seconds, bpm); pace and h:mm are formatted by the presentation layer.
"""

import datetime as dt
import logging
import math

import pandas as pd
from sqlalchemy import select
from sqlmodel import Session

from training import pipeline
from training.db.models import Activity, ActivityMetric, BestEffort, CurveSnapshot
from training.metrics.efficiency import TREND_WINDOW_DAYS, ef_trend
from training.metrics.efforts import (
    TRAILING_DAYS,
    ThresholdProposal,
    best_per_window,
    propose_lthr,
    propose_threshold_speed,
)
from training.metrics.predictions import is_stale, pick_reference, predict
from training.services.dto import (
    BestEffortDTO,
    BestEffortsDTO,
    CurveBinDTO,
    CurveDTO,
    PredictionDTO,
    PredictionsDTO,
    ProposalDTO,
    ReferenceDTO,
    SeriesDTO,
    SeriesPointDTO,
    ThresholdDTO,
    ThresholdIn,
    TrendPointDTO,
)
from training.services.errors import InvalidInputError
from training.services.garmin_values import garmin_values, number

log = logging.getLogger(__name__)

SERIES_METRICS: dict[str, tuple[str, str]] = {  # metric → (ActivityMetric column, unit)
    "ef": ("ef", "m/min/bpm"),
    "decoupling_pct": ("decoupling_pct", "%"),
    "pace_at_ref_hr_day": ("pace_at_ref_hr_day", "m/s"),
}
SERIES_SPORTS = ("run", "bike")
EFFORT_RANGES = ("90d", "all")
MAX_DAYS = 3650
MAX_MONTHS = 120
BIKE_CAVEAT = "Bike EF depends on terrain and wind - use the trend only, not single rides."


# --- EF / decoupling / pace at reference HR --------------------------------------------------------------


def get_ef_series(
    session: Session, *, sport: str = "run", days: int = 180, today: dt.date, metric: str = "ef"
) -> SeriesDTO:
    """Per-activity values of `metric` over the last `days` days plus the 28-day median trend (§5.2).

    EF and decoupling points are steady-state activities only (§5.1); `pace_at_ref_hr_day` (§6.1) has no
    steady-state condition and exists for runs only. The trend is `ef_trend` over the metric column – the
    same median rule for all three metrics.
    """
    if metric not in SERIES_METRICS:
        raise InvalidInputError(f"metric must be one of {', '.join(SERIES_METRICS)}")
    if sport not in SERIES_SPORTS:
        raise InvalidInputError(f"sport must be one of {', '.join(SERIES_SPORTS)}")
    if not 1 <= days <= MAX_DAYS:
        raise InvalidInputError(f"days must be between 1 and {MAX_DAYS}")
    column, unit = SERIES_METRICS[metric]
    start = today - dt.timedelta(days=days - 1)
    rows = session.execute(
        select(Activity.id, Activity.local_date, getattr(ActivityMetric, column), ActivityMetric.steady_state)
        .join(ActivityMetric, ActivityMetric.activity_id == Activity.id)
        .where(
            Activity.sport == sport,
            Activity.local_date >= start - dt.timedelta(days=TREND_WINDOW_DAYS - 1),  # trend look-back
            Activity.local_date <= today,
        )
        .order_by(Activity.local_date, Activity.id)
    ).all()
    steady_only = metric != "pace_at_ref_hr_day"
    supported = sport == "run" or metric != "pace_at_ref_hr_day"  # pace at ref HR is defined for runs only
    usable = [
        r
        for r in rows
        if supported and r[2] is not None and math.isfinite(r[2]) and (r[3] is True or not steady_only)
    ]
    day_list = [start + dt.timedelta(days=i) for i in range(days)]
    trend: list[TrendPointDTO] = []
    if usable:
        frame = pd.DataFrame(
            {
                "local_date": [r[1] for r in usable],
                "ef": [float(r[2]) for r in usable],  # ef_trend's column name, whatever the metric
                "steady_state": [True] * len(usable),  # the filter above already applied the §5.1 rule
            }
        )
        values = ef_trend(frame, day_list).tolist()
        trend = [
            TrendPointDTO(date=d, value=None if math.isnan(v) else float(v))
            for d, v in zip(day_list, values, strict=True)
        ]
    return SeriesDTO(
        metric=metric,
        sport=sport,
        unit=unit,
        points=[
            SeriesPointDTO(activity_id=r[0], local_date=r[1], value=float(r[2]), steady_state=r[3])
            for r in usable
            if r[1] >= start
        ],
        trend=trend,
        caveat=BIKE_CAVEAT if sport == "bike" and metric != "pace_at_ref_hr_day" else None,
    )


# --- speed–HR curves -------------------------------------------------------------------------------------


def _curve_dto(snapshot: CurveSnapshot) -> CurveDTO:
    raw = snapshot.curve if isinstance(snapshot.curve, dict) else {}
    bins_raw = raw.get("bins") if isinstance(raw.get("bins"), dict) else {}
    counts = raw.get("counts") if isinstance(raw.get("counts"), dict) else {}
    bins: list[CurveBinDTO] = []
    for key, speed in bins_raw.items():
        try:
            hr_bin = int(key)
        except (TypeError, ValueError):
            continue
        value = number(speed)
        if value is None or value <= 0:
            continue
        bins.append(CurveBinDTO(hr_bin=hr_bin, gap_speed=value, count=int(number(counts.get(key)) or 0)))
    bins.sort(key=lambda b: b.hr_bin)
    return CurveDTO(
        month=snapshot.month,
        sport=snapshot.sport,
        bins=bins,
        ref_hr=number(raw.get("ref_hr")),
        pace_at_ref_hr=number(raw.get("pace_at_ref_hr")),
    )


def _oldest_month(today: dt.date, months: int) -> str:
    """The "YYYY-MM" of the oldest month of a window of `months` calendar months ending in today's month."""
    index = today.year * 12 + today.month - 1 - (months - 1)
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


def get_speed_hr_curves(session: Session, *, months: int = 6, today: dt.date) -> list[CurveDTO]:
    """The month-end snapshots (§6.1) of the last `months` calendar months, oldest first (run)."""
    if not 1 <= months <= MAX_MONTHS:
        raise InvalidInputError(f"months must be between 1 and {MAX_MONTHS}")
    rows = session.execute(
        select(CurveSnapshot)
        .where(
            CurveSnapshot.sport == "run",
            CurveSnapshot.month >= _oldest_month(today, months),
            CurveSnapshot.month <= f"{today:%Y-%m}",
        )
        .order_by(CurveSnapshot.month)
    ).scalars()
    return [_curve_dto(s) for s in rows]


# --- best efforts ----------------------------------------------------------------------------------------

_EFFORT_COLUMNS = ["activity_id", "local_date", "kind", "window_s", "value", "distance_m"]


def _effort_frame(session: Session, sport: str) -> pd.DataFrame:
    rows = session.execute(
        select(
            BestEffort.activity_id,
            Activity.local_date,
            BestEffort.kind,
            BestEffort.window_s,
            BestEffort.value,
            BestEffort.distance_m,
        )
        .join(Activity, Activity.id == BestEffort.activity_id)
        .where(BestEffort.sport == sport)
    ).all()
    return pd.DataFrame(rows, columns=_EFFORT_COLUMNS)


def get_best_efforts(
    session: Session, *, sport: str = "run", range: str = "90d", today: dt.date
) -> BestEffortsDTO:
    """Best value per (kind, window) over the trailing 90 days or all time (§6.2)."""
    if sport not in SERIES_SPORTS:
        raise InvalidInputError(f"sport must be one of {', '.join(SERIES_SPORTS)}")
    if range not in EFFORT_RANGES:
        raise InvalidInputError(f"range must be one of {', '.join(EFFORT_RANGES)}")
    frame = _effort_frame(session, sport)
    best = best_per_window(frame, today=today, days=TRAILING_DAYS if range == "90d" else None)
    distance = {(r.activity_id, r.kind, r.window_s): r.distance_m for r in frame.itertuples()}
    efforts = [
        BestEffortDTO(
            kind=r.kind,
            window_s=int(r.window_s),
            value=float(r.value),
            local_date=r.local_date,
            activity_id=int(r.activity_id),
            distance_m=number(distance.get((r.activity_id, r.kind, r.window_s))),
        )
        for r in best.itertuples()
    ]
    return BestEffortsDTO(sport=sport, range=range, efforts=efforts)


# --- predictions -----------------------------------------------------------------------------------------


def _prediction_candidates(session: Session) -> pd.DataFrame:
    """§7 candidates: run races (distance, duration) and run gap_speed efforts W ≥ 600 s (distance, W)."""
    races = session.execute(
        select(Activity.local_date, Activity.distance_m, Activity.duration_s).where(
            Activity.sport == "run", Activity.is_race.is_(True)
        )
    ).all()
    efforts = session.execute(
        select(Activity.local_date, BestEffort.distance_m, BestEffort.window_s)
        .join(Activity, Activity.id == BestEffort.activity_id)
        .where(
            BestEffort.sport == "run",
            BestEffort.kind == "gap_speed",
            BestEffort.window_s >= 600,
            BestEffort.distance_m.is_not(None),
        )
    ).all()
    records = [(*r, "race") for r in races] + [(*r, "effort") for r in efforts]
    return pd.DataFrame(records, columns=["local_date", "distance_m", "time_s", "source"])


def get_predictions(session: Session, *, today: dt.date) -> PredictionsDTO:
    """Riegel and Daniels predictions from the best recent reference performance (§7)."""
    reference = pick_reference(_prediction_candidates(session), today=today)
    if reference is None:
        return PredictionsDTO(reference=None, stale=False, predictions=[])
    return PredictionsDTO(
        reference=ReferenceDTO(
            distance_m=reference.distance_m,
            time_s=reference.time_s,
            local_date=reference.local_date,
            source=reference.source,
            vdot=reference.vdot,
        ),
        stale=is_stale(reference, today),
        predictions=[
            PredictionDTO(
                name=p.name,
                distance_m=p.distance_m,
                riegel_s=p.riegel_s,
                daniels_s=p.daniels_s,
                extrapolated=p.extrapolated,
            )
            for p in predict(reference)
        ],
    )


# --- threshold proposals ---------------------------------------------------------------------------------


def _activity_frame(session: Session, sport: str) -> pd.DataFrame:
    rows = session.execute(
        select(
            Activity.id,
            Activity.local_date,
            Activity.sport,
            ActivityMetric.if_pace,
            ActivityMetric.hrtss,
            Activity.moving_s,
        )
        .join(ActivityMetric, ActivityMetric.activity_id == Activity.id)
        .where(Activity.sport == sport)
    ).all()
    return pd.DataFrame(rows, columns=["activity_id", "local_date", "sport", "if_pace", "hrtss", "moving_s"])


def _proposal_dto(
    p: ThresholdProposal, garmin: tuple[float | None, float | None, float | None]
) -> ProposalDTO:
    lthr, speed, vo2max = garmin
    is_run = p.sport == "run"  # Garmin's lactate threshold / VO2max values are running values
    return ProposalDTO(
        sport=p.sport,
        field=p.field,
        current=number(p.current),
        estimate=float(p.estimate),
        change=number(p.change),
        propose=bool(p.propose),
        basis=p.basis,
        garmin_lthr=lthr if is_run else None,
        garmin_lt_speed=speed if is_run else None,
        garmin_vo2max=vo2max if is_run else None,
    )


def get_threshold_proposals(session: Session, *, today: dt.date) -> list[ProposalDTO]:
    """Run threshold speed, run LTHR and bike LTHR estimates (§6.3) against the thresholds valid today.

    Estimates without enough data are left out. Nothing is applied here (see `apply_proposal`).
    """
    current = {s: pipeline.resolve_threshold(session, s, today) for s in SERIES_SPORTS}
    garmin = garmin_values(session)
    run_efforts = _effort_frame(session, "run")
    found: list[ThresholdProposal | None] = [
        propose_threshold_speed(
            run_efforts, current=current["run"].threshold_speed if current["run"] else None, today=today
        )
    ]
    for sport in SERIES_SPORTS:
        efforts = run_efforts if sport == "run" else _effort_frame(session, sport)
        found.append(
            propose_lthr(
                sport,
                efforts[efforts["kind"] == "hr"],
                _activity_frame(session, sport),
                current=current[sport].lthr if current[sport] else None,
                today=today,
            )
        )
    return [_proposal_dto(p, garmin) for p in found if p is not None]


def apply_proposal(session: Session, *, sport: str, field: str, today: dt.date) -> ThresholdDTO:
    """Store the current proposal for (sport, field) as a threshold valid from `today` (source "proposal").

    The estimate is recomputed here, never taken from the caller. The stored record also carries the other
    value valid today (a speed proposal keeps the LTHR and vice versa): thresholds are versioned per record.
    """
    from training.services import settings as settings_service  # local: keeps the import graph shallow

    proposal = next(
        (p for p in get_threshold_proposals(session, today=today) if p.sport == sport and p.field == field),
        None,
    )
    if proposal is None:
        raise InvalidInputError(f"no {field} proposal for {sport} (not enough data)")
    current = pipeline.resolve_threshold(session, sport, today)
    lthr = proposal.estimate if field == "lthr" else (current.lthr if current else None)
    speed = (
        proposal.estimate if field == "threshold_speed" else (current.threshold_speed if current else None)
    )
    if lthr is None:
        raise InvalidInputError("set an LTHR first: a pace proposal is stored together with the current LTHR")
    data = ThresholdIn(sport=sport, valid_from=today, lthr=lthr, threshold_speed=speed, source="proposal")
    return settings_service.add_threshold(session, data, today=today)
