"""Incremental sync (PLAN.md phase 1): activities since last_activity_sync − 2 days, wellness from
last_wellness_date to today.

Idempotent (CLAUDE.md rule 5): raw payloads are upserted by (kind, ref_key), activities by garmin_id,
wellness by date. An already-known activity is only re-fetched when its list item changed. Raw payloads are
committed as soon as they arrive, so a crash or Ctrl+C never loses downloaded data; normalization runs from
raw_garmin via training.db.rebuild.
"""

import datetime as dt
import logging
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session

from training.db import rebuild, repo
from training.garmin import endpoints as ep
from training.garmin.client import (
    GarminClient,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

log = logging.getLogger(__name__)

LAST_ACTIVITY_SYNC = "last_activity_sync"
LAST_WELLNESS_DATE = "last_wellness_date"
ACTIVITY_OVERLAP_DAYS = 2
FIRST_SYNC_DAYS = 14


@dataclass
class SyncResult:
    activities_new: int = 0
    activities_updated: int = 0
    activities_unchanged: int = 0
    wellness_days: int = 0
    errors: list[str] = field(default_factory=list)

    def merge(self, other: "SyncResult") -> None:
        self.activities_new += other.activities_new
        self.activities_updated += other.activities_updated
        self.activities_unchanged += other.activities_unchanged
        self.wellness_days += other.wellness_days
        self.errors.extend(other.errors)


def raw_sink_for(session: Session):  # type: ignore[no-untyped-def]
    """Raw sink that persists and commits every Garmin response immediately."""

    def sink(kind: str, ref_key: str, payload: Any) -> None:
        repo.store_raw(session, kind, ref_key, payload)
        session.commit()

    return sink


class Ingestor:
    """Fetch → raw_garmin → normalize, shared by sync and backfill."""

    def __init__(self, session: Session, client: GarminClient) -> None:
        self.session = session
        self.client = client
        if client.raw_sink is None:
            client.raw_sink = raw_sink_for(session)

    def _optional(self, label: str, fn, *args: Any, errors: list[str]) -> Any:  # type: ignore[no-untyped-def]
        """Call an endpoint whose failure should not stop the run (404, other 4xx, exhausted 5xx)."""
        try:
            return fn(*args)
        except (GarminConnectAuthenticationError, GarminConnectTooManyRequestsError):
            raise
        except (GarminConnectConnectionError, ValueError) as exc:
            log.warning("%s failed: %s", label, type(exc).__name__)
            errors.append(f"{label}: {type(exc).__name__}")
            return None

    def activities(self, start: dt.date, end: dt.date) -> SyncResult:
        result = SyncResult()
        for item in self.client.activities_by_date(start, end):
            garmin_id = item.get("activityId")
            if garmin_id is None:
                continue
            changed = repo.store_raw(self.session, ep.ACTIVITY_LIST_ITEM, str(garmin_id), item)
            self.session.commit()
            known = repo.activity_id_for(self.session, garmin_id) is not None
            if known and not changed:
                result.activities_unchanged += 1
                continue
            label = f"activity {garmin_id}"
            self._optional(label + " summary", self.client.activity_summary, garmin_id, errors=result.errors)
            duration = item.get("elapsedDuration") or item.get("duration")
            self._optional(
                label + " details", self.client.activity_details, garmin_id, duration, errors=result.errors
            )
            self._optional(label + " splits", self.client.activity_splits, garmin_id, errors=result.errors)
            self._optional(
                label + " hr zones", self.client.activity_hr_zones, garmin_id, errors=result.errors
            )
            try:
                rebuild.rebuild_activity(self.session, garmin_id)
                self.session.commit()
            except Exception as exc:  # raw data is already safe; report and continue
                self.session.rollback()
                log.exception("normalizing %s failed", label)
                result.errors.append(f"{label} normalize: {type(exc).__name__}")
                continue
            if known:
                result.activities_updated += 1
            else:
                result.activities_new += 1
        return result

    def wellness_day(self, day: dt.date, errors: list[str]) -> None:
        for kind, fn in (
            (ep.SLEEP, self.client.sleep),
            (ep.USER_SUMMARY, self.client.user_summary),
            (ep.RHR, self.client.rhr),
            (ep.STRESS, self.client.stress),
            (ep.BODY_BATTERY, self.client.body_battery),
        ):
            self._optional(f"{kind} {day}", fn, day, errors=errors)
        try:
            rebuild.rebuild_wellness_day(self.session, day)
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            log.exception("normalizing wellness %s failed", day)
            errors.append(f"wellness {day} normalize: {type(exc).__name__}")

    def status(self, day: dt.date, errors: list[str]) -> None:
        """Current Garmin training status / VO2max / lactate threshold – raw only (used from phase 4)."""
        self._optional(f"training_status {day}", self.client.training_status, day, errors=errors)
        self._optional(f"max_metrics {day}", self.client.max_metrics, day, errors=errors)
        self._optional(f"lactate_threshold {day}", self.client.lactate_threshold, day, errors=errors)


def _days(start: dt.date, end: dt.date) -> list[dt.date]:
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def sync(session: Session, client: GarminClient, today: dt.date) -> SyncResult:
    """Incremental sync up to `today` (local date). Safe to run any number of times."""
    ingest = Ingestor(session, client)
    last_act = repo.get_state_date(session, LAST_ACTIVITY_SYNC)
    act_start = (last_act or today - dt.timedelta(days=FIRST_SYNC_DAYS)) - dt.timedelta(
        days=ACTIVITY_OVERLAP_DAYS
    )
    result = ingest.activities(act_start, today)
    repo.set_state(session, LAST_ACTIVITY_SYNC, today.isoformat())
    session.commit()

    last_well = repo.get_state_date(session, LAST_WELLNESS_DATE)
    well_start = last_well or today - dt.timedelta(days=FIRST_SYNC_DAYS)
    for day in _days(min(well_start, today), today):
        ingest.wellness_day(day, result.errors)
        result.wellness_days += 1
        repo.set_state(session, LAST_WELLNESS_DATE, day.isoformat())
        session.commit()

    ingest.status(today, result.errors)
    log.info(
        "sync done: %d new, %d updated, %d unchanged activities; %d wellness days; %d errors",
        result.activities_new,
        result.activities_updated,
        result.activities_unchanged,
        result.wellness_days,
        len(result.errors),
    )
    return result
