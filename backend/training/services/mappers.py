"""DB row → DTO mappers shared by the services (no queries here, no formulas)."""

from collections.abc import Sequence
from typing import Any

from training.db.models import Activity, ActivityMetric, Subjective, Threshold
from training.metrics.zones import HR_ZONE_BOUNDS, PACE_ZONE_BOUNDS, ZONE_KEYS, default_zones
from training.services.dto import (
    ActivitySummaryDTO,
    SubjectiveDTO,
    ThresholdDTO,
    ZoneBoundDTO,
    ZoneTimeDTO,
)


def threshold_dto(t: Threshold) -> ThresholdDTO:
    assert t.id is not None
    return ThresholdDTO(
        id=t.id,
        sport=t.sport,
        valid_from=t.valid_from,
        lthr=t.lthr,
        threshold_speed=t.threshold_speed,
        zones=t.zones or default_zones(),
        source=t.source,
    )


def zone_bounds(fractions: Sequence[float], reference: float) -> list[ZoneBoundDTO]:
    """Five zones from the four METRICS §1 fractions × `reference` (LTHR in bpm or threshold speed in m/s).

    Zone 1 has no lower and zone 5 no upper bound (null = open).
    """
    edges: list[float | None] = [None, *(f * reference for f in fractions), None]
    return [ZoneBoundDTO(zone=i + 1, lower=edges[i], upper=edges[i + 1]) for i in range(5)]


def hr_zone_bounds(t: Threshold) -> list[ZoneBoundDTO]:
    assert t.lthr
    return zone_bounds((t.zones or {}).get("hr", HR_ZONE_BOUNDS), t.lthr)


def pace_zone_bounds(t: Threshold) -> list[ZoneBoundDTO]:
    assert t.threshold_speed
    return zone_bounds((t.zones or {}).get("pace", PACE_ZONE_BOUNDS), t.threshold_speed)


def zone_times(seconds: dict[str, Any] | None, bounds: list[ZoneBoundDTO]) -> list[ZoneTimeDTO]:
    """`time_in_*_zone` JSON (`{"1": s, …}`) + the bounds of the threshold used → ZoneTimeDTO list.

    Empty when there is no time in any zone (no HR / no valid samples).
    """
    if not isinstance(seconds, dict):
        return []
    values = [int(seconds.get(key) or 0) for key in ZONE_KEYS]
    total = sum(values)
    if total == 0:
        return []
    return [
        ZoneTimeDTO(zone=b.zone, seconds=s, share=s / total, lower=b.lower, upper=b.upper)
        for b, s in zip(bounds, values, strict=True)
    ]


def summary_dto(a: Activity, m: ActivityMetric | None) -> ActivitySummaryDTO:
    assert a.id is not None
    return ActivitySummaryDTO(
        id=a.id,
        garmin_id=a.garmin_id,
        sport=a.sport,
        sub_sport=a.sub_sport,
        name=a.name,
        local_date=a.local_date,
        start_utc=a.start_utc,
        tz=a.tz,
        duration_s=a.duration_s,
        moving_s=a.moving_s,
        distance_m=a.distance_m,
        elev_gain_m=a.elev_gain_m,
        avg_hr=a.avg_hr,
        max_hr=a.max_hr,
        avg_speed=a.avg_speed,
        is_race=a.is_race,
        is_indoor=a.is_indoor,
        load_primary=m.load_primary if m else None,
        load_method=m.load_method if m else None,
        hrtss=m.hrtss if m else None,
        rtss=m.rtss if m else None,
        trimp_norm=m.trimp_norm if m else None,
        if_hr=m.if_hr if m else None,
        if_pace=m.if_pace if m else None,
        hr_coverage=m.hr_coverage if m else None,
        low_confidence=m.low_confidence if m else False,
        garmin_training_load=a.garmin_training_load,
    )


def subjective_dto(s: Subjective) -> SubjectiveDTO:
    assert s.id is not None
    return SubjectiveDTO(
        id=s.id,
        date=s.date,
        activity_id=s.activity_id,
        rpe=s.rpe,
        feel=s.feel,
        soreness=s.soreness,
        notes=s.notes,
    )
