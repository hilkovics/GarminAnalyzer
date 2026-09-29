"""Manual sync service ("Run sync now", `POST /api/sync`): the CLI's `training sync`, run synchronously.

Garmin → raw_garmin → typed tables (`garmin.sync.sync`) → metrics and PMC (`pipeline.update_after_sync`).
Expected failures become `ServiceError`s with a short fixed message; nothing from the Garmin exception (which
could echo paths or tokens) is passed on (CLAUDE.md rule 8). Progress is committed as it arrives, so a failed
run is resumed by the next one.
"""

import datetime as dt
import logging

import requests
from sqlmodel import Session

from training import pipeline
from training.config import Settings
from training.garmin import sync as garmin_sync
from training.garmin.client import (
    GarminClient,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)
from training.services.dto import SyncResultDTO
from training.services.errors import ServiceError

log = logging.getLogger(__name__)

AUTH_MESSAGE = "Garmin login is missing or was rejected. Run `training login` and try again."
RATE_LIMIT_MESSAGE = "Garmin is rate-limiting requests (429). Progress is saved; try again in a while."
NETWORK_MESSAGE = "Garmin Connect is unreachable or failing. Progress is saved; try again later."


def run_sync(session: Session, *, settings: Settings, today: dt.date) -> SyncResultDTO:
    """Incremental sync up to `today`, then metrics for everything it changed."""
    try:
        client = GarminClient.from_settings(settings, raw_sink=garmin_sync.raw_sink_for(session))
        synced = garmin_sync.sync(session, client, today)
    except GarminConnectAuthenticationError:
        raise ServiceError(AUTH_MESSAGE) from None
    except GarminConnectTooManyRequestsError:
        raise ServiceError(RATE_LIMIT_MESSAGE) from None
    except (GarminConnectConnectionError, requests.ConnectionError, requests.Timeout) as exc:
        log.warning("sync failed: %s", type(exc).__name__)
        raise ServiceError(NETWORK_MESSAGE) from None
    computed = pipeline.update_after_sync(session, synced.affected, today=today)
    return SyncResultDTO(
        activities_new=synced.activities_new,
        activities_updated=synced.activities_updated,
        activities_unchanged=synced.activities_unchanged,
        activities_pending=synced.activities_pending,
        activities_failed=synced.activities_failed,
        wellness_days=synced.wellness_days,
        metrics_computed=computed.metrics_computed,
        pmc_days=computed.daily_load_days,
        errors=[*synced.errors, *computed.errors],
    )
