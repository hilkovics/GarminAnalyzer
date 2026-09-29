"""Push planned workouts to Garmin Connect (phase 7, METRICS §10.8): POST /plan/{id}/push, push-today.

The push itself lives in `training.push`; this maps it to DTOs and turns Garmin failures into `ServiceError`s
with a short fixed message – nothing from the Garmin exception (which could echo paths or tokens) is passed
on (CLAUDE.md rule 8).
"""

import datetime as dt
import logging

import requests
from sqlmodel import Session

from training import planning, push
from training.coach.garmin_push import PushError
from training.config import Settings
from training.garmin.client import (
    GarminClient,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
    http_status,
)
from training.services.dto_plan import PushResultDTO
from training.services.errors import InvalidInputError, NotFoundError, ServiceError
from training.services.sync import AUTH_MESSAGE, NETWORK_MESSAGE, RATE_LIMIT_MESSAGE

log = logging.getLogger(__name__)

REJECTED_MESSAGE = "Garmin Connect rejected the workout. Try again later or check the plan."


def _dto(result: push.PushResult) -> PushResultDTO:
    return PushResultDTO(
        planned_id=result.planned_id,
        action=result.action,
        garmin_workout_id=result.garmin_workout_id,
        scheduled_date=result.scheduled_date,
        payload=result.payload,
        notes=result.notes,
    )


def _run(fn, session: Session, settings: Settings, dry_run: bool):
    """Build the Garmin client (unless dry run) and run `fn`; roll back on any failure."""
    try:
        client = None if dry_run else GarminClient.from_settings(settings)
        return fn(client)
    except Exception:
        session.rollback()  # a failed write must not poison the session for the caller
        raise


def _mapped(fn, session: Session, settings: Settings, dry_run: bool):
    """`_run` with every failure mapped to a service error (fixed messages, no Garmin exception text)."""
    try:
        return _run(fn, session, settings, dry_run)
    except (planning.PlanError, PushError) as exc:
        raise InvalidInputError(str(exc)) from exc
    except LookupError as exc:
        raise NotFoundError(str(exc)) from exc
    except GarminConnectAuthenticationError:
        raise ServiceError(AUTH_MESSAGE) from None
    except GarminConnectTooManyRequestsError:
        raise ServiceError(RATE_LIMIT_MESSAGE) from None
    except GarminConnectConnectionError as exc:
        status = http_status(exc)
        log.warning("Garmin push failed: %s status=%s", type(exc).__name__, status)
        if status == 429:
            raise ServiceError(RATE_LIMIT_MESSAGE) from None
        if status in (401, 403):
            raise ServiceError(AUTH_MESSAGE) from None
        raise ServiceError(REJECTED_MESSAGE if status and 400 <= status < 500 else NETWORK_MESSAGE) from None
    except (requests.ConnectionError, requests.Timeout) as exc:
        log.warning("Garmin push failed: %s", type(exc).__name__)
        raise ServiceError(NETWORK_MESSAGE) from None


def push_planned(
    session: Session, planned_id: int, *, settings: Settings, dry_run: bool = False
) -> PushResultDTO:
    def run(client):
        return _dto(push.push_planned(session, client, planned_id, dry_run=dry_run))

    return _mapped(run, session, settings, dry_run)


def push_day(
    session: Session, day: dt.date, *, settings: Settings, dry_run: bool = False
) -> list[PushResultDTO]:
    def run(client):
        return [_dto(r) for r in push.push_day(session, client, day, dry_run=dry_run)]

    return _mapped(run, session, settings, dry_run)
