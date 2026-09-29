"""Settings services: athlete, historical thresholds with zone bounds, threshold/athlete updates.

Writes go through `training.pipeline` (`set_threshold`, `set_athlete`, `recompute`), which also recomputes the
affected metrics – a new LTHR only changes activities from its `valid_from` on (CLAUDE.md rule 7).
"""

import datetime as dt
import math

from sqlalchemy import select
from sqlmodel import Session

from training import pipeline
from training.db.models import Athlete, Threshold
from training.metrics.preprocess import HR_MAX, HR_MIN, MAX_SPEED
from training.services.dto import (
    AthleteDTO,
    AthleteIn,
    SettingsDTO,
    ThresholdDTO,
    ThresholdIn,
    ZoneBoundDTO,
)
from training.services.errors import InvalidInputError
from training.services.mappers import hr_zone_bounds, pace_zone_bounds, threshold_dto

THRESHOLD_SPORTS = ("run", "bike")
SEXES = ("male", "female")
MIN_THRESHOLD_SPEED = 0.5  # m/s
METRIC_FIELDS = ("sex", "max_hr", "rest_hr_override")  # athlete fields that change TRIMP (METRICS §2.2)


def get_settings(session: Session, *, today: dt.date) -> SettingsDTO:
    """Athlete, the full threshold history, the thresholds valid `today` and their absolute zone bounds."""
    history = session.execute(select(Threshold).order_by(Threshold.sport, Threshold.valid_from)).scalars()
    current = {sport: pipeline.resolve_threshold(session, sport, today) for sport in THRESHOLD_SPORTS}
    hr_zones: dict[str, list[ZoneBoundDTO]] = {
        sport: hr_zone_bounds(t) for sport, t in current.items() if t is not None and t.lthr
    }
    run = current["run"]
    return SettingsDTO(
        athlete=_athlete_dto(session, today),
        thresholds=[threshold_dto(t) for t in history],
        current={sport: threshold_dto(t) if t is not None else None for sport, t in current.items()},
        hr_zones=hr_zones,
        pace_zones=pace_zone_bounds(run) if run is not None and run.threshold_speed else None,
    )


def add_threshold(session: Session, data: ThresholdIn, *, today: dt.date) -> ThresholdDTO:
    """Add or replace the threshold of (sport, valid_from) and recompute the activities from that date on."""
    if data.sport not in THRESHOLD_SPORTS:
        raise InvalidInputError(f"sport must be one of {', '.join(THRESHOLD_SPORTS)}")
    if data.sport == "bike" and data.threshold_speed is not None:
        raise InvalidInputError("threshold_speed (pace) is only used for run thresholds")
    if not HR_MIN <= data.lthr <= HR_MAX:
        raise InvalidInputError(f"lthr must be between {HR_MIN:.0f} and {HR_MAX:.0f} bpm")
    speed = data.threshold_speed
    if speed is not None and not (math.isfinite(speed) and MIN_THRESHOLD_SPEED <= speed <= MAX_SPEED["run"]):
        raise InvalidInputError(
            f"threshold_speed must be between {MIN_THRESHOLD_SPEED} and {MAX_SPEED['run']} m/s"
        )
    pipeline.set_threshold(
        session,
        sport=data.sport,
        valid_from=data.valid_from,
        lthr=data.lthr,
        threshold_speed=speed,
        end=today,
    )
    stored = session.execute(
        select(Threshold).where(Threshold.sport == data.sport, Threshold.valid_from == data.valid_from)
    ).scalar_one()
    return threshold_dto(stored)


def update_athlete(session: Session, data: AthleteIn, *, today: dt.date) -> AthleteDTO:
    """Update the given (non-null) athlete fields; TRIMP-relevant changes recompute all metrics."""
    fields = data.model_dump(exclude={"clear_rest_hr_override"})
    given = {k: v for k, v in fields.items() if v is not None}
    if data.clear_rest_hr_override and data.rest_hr_override is not None:
        raise InvalidInputError("rest_hr_override and clear_rest_hr_override are mutually exclusive")
    if not given and not data.clear_rest_hr_override:
        raise InvalidInputError("no athlete field given")
    if data.sex is not None and data.sex not in SEXES:
        raise InvalidInputError(f"sex must be one of {', '.join(SEXES)}")
    if data.birth_year is not None and not 1900 <= data.birth_year <= today.year:
        raise InvalidInputError(f"birth_year must be between 1900 and {today.year}")
    athlete = pipeline.get_athlete(session)
    if athlete is None and not given:
        raise InvalidInputError("no athlete settings to clear yet")
    athlete = athlete or Athlete()
    before = {k: getattr(athlete, k) for k in METRIC_FIELDS}
    for key, value in given.items():
        setattr(athlete, key, value)
    if data.clear_rest_hr_override:
        athlete.rest_hr_override = None
    session.add(athlete)
    session.commit()  # one atomic write
    if any(getattr(athlete, k) != before[k] for k in METRIC_FIELDS):  # only real TRIMP-relevant changes
        pipeline.recompute(session, renormalize=False, end=today)
    dto = _athlete_dto(session, today)
    assert dto is not None
    return dto


def _athlete_dto(session: Session, today: dt.date) -> AthleteDTO | None:
    athlete: Athlete | None = pipeline.get_athlete(session)
    if athlete is None:
        return None
    return AthleteDTO(
        sex=athlete.sex,
        birth_year=athlete.birth_year,
        max_hr=athlete.max_hr,
        rest_hr_override=athlete.rest_hr_override,
        rest_hr_current=pipeline.rest_hr_for(session, athlete, today),
        weight_kg=athlete.weight_kg,
        run_bike_split=athlete.run_bike_split,
    )
