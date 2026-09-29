"""Hand-built sample DTOs for the Progres page and its components (contract: services/dto.py)."""

import datetime as dt

from tests.test_ui_support import TODAY
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
    TrendPointDTO,
)


def sample_series(
    metric: str = "ef", *, sport: str = "run", n: int = 4, caveat=None, trend=True
) -> SeriesDTO:
    unit = {"ef": "m/min/bpm", "decoupling_pct": "%", "pace_at_ref_hr_day": "m/s"}[metric]
    base = {"ef": 1.5, "decoupling_pct": 4.0, "pace_at_ref_hr_day": 3.5}[metric]
    days = [TODAY - dt.timedelta(days=7 * (n - i)) for i in range(n)]
    points = [
        SeriesPointDTO(activity_id=i + 1, local_date=d, value=base + i * 0.1, steady_state=True)
        for i, d in enumerate(days)
    ]
    line = [
        TrendPointDTO(date=TODAY - dt.timedelta(days=30 - i), value=None if i < 3 else base + 0.05)
        for i in range(30)
    ]
    return SeriesDTO(
        metric=metric,
        sport=sport,
        unit=unit,
        points=points,
        trend=line if trend and days else [],
        caveat=caveat,
    )


def empty_series(metric: str = "ef", sport: str = "run") -> SeriesDTO:
    return sample_series(metric, sport=sport, n=0, trend=False)


def sample_curves() -> list[CurveDTO]:
    def curve(month: str, shift: float) -> CurveDTO:
        bins = [
            CurveBinDTO(hr_bin=hr, gap_speed=2.8 + (hr - 130) * 0.02 + shift, count=12 + hr // 10)
            for hr in (130, 135, 140, 145, 150)
        ]
        return CurveDTO(month=month, sport="run", bins=bins, ref_hr=136.0, pace_at_ref_hr=3.0 + shift)

    return [curve("2026-07", 0.0), curve("2026-08", 0.05), curve("2026-09", 0.1)]


def effort(kind: str, window_s: int, value: float, day: dt.date, distance: float | None = None):
    return BestEffortDTO(
        kind=kind, window_s=window_s, value=value, local_date=day, activity_id=1, distance_m=distance
    )


def sample_efforts(range_: str = "90d", sport: str = "run") -> BestEffortsDTO:
    recent = range_ == "90d"
    day = TODAY - dt.timedelta(days=20 if recent else 400)
    speed_kind = "gap_speed" if sport == "run" else "speed"
    factor = 1.0 if recent else 1.05
    efforts = [
        effort(speed_kind, w, (5.0 - i * 0.3) * factor, day, distance=w * 4.0)
        for i, w in enumerate((60, 300, 600, 1200, 1800, 3600))
    ] + [effort("hr", w, 165.0 - i * 3, day) for i, w in enumerate((1200, 1800, 3600))]
    return BestEffortsDTO(sport=sport, range=range_, efforts=efforts)


def sample_predictions(*, stale: bool = False) -> PredictionsDTO:
    return PredictionsDTO(
        reference=ReferenceDTO(
            distance_m=10000.0,
            time_s=2400.0,
            local_date=TODAY - dt.timedelta(days=70 if stale else 10),
            source="race",
            vdot=51.94,
        ),
        stale=stale,
        predictions=[
            PredictionDTO(
                name="5k", distance_m=5000.0, riegel_s=1150.0, daniels_s=1155.0, extrapolated=False
            ),
            PredictionDTO(
                name="10k", distance_m=10000.0, riegel_s=2400.0, daniels_s=2400.0, extrapolated=False
            ),
            PredictionDTO(
                name="half", distance_m=21097.5, riegel_s=5265.0, daniels_s=5313.0, extrapolated=False
            ),
            PredictionDTO(
                name="marathon", distance_m=42195.0, riegel_s=11000.0, daniels_s=11250.0, extrapolated=True
            ),
        ],
    )


def sample_proposals(*, propose: bool = True) -> list[ProposalDTO]:
    return [
        ProposalDTO(
            sport="run",
            field="threshold_speed",
            current=3.5,
            estimate=3.7,
            change=3.7 / 3.5 - 1,
            propose=propose,
            basis="best 1800 s GAP (2026-09-01)",
            garmin_lthr=171.0,
            garmin_lt_speed=3.6,
            garmin_vo2max=52.4,
        ),
        ProposalDTO(
            sport="run",
            field="lthr",
            current=170.0,
            estimate=174.0,
            change=4.0,
            propose=propose,
            basis="max 1800 s HR effort",
            garmin_lthr=171.0,
            garmin_lt_speed=3.6,
            garmin_vo2max=52.4,
        ),
        ProposalDTO(
            sport="bike",
            field="lthr",
            current=165.0,
            estimate=166.0,
            change=1.0,
            propose=False,
            basis="max 1800 s HR effort",
            garmin_lthr=None,
            garmin_lt_speed=None,
            garmin_vo2max=None,
        ),
    ]
