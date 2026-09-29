"""Incremental sync (PLAN.md phase 1): activities since last_activity_sync − 2 days, wellness from
last_wellness_date to today.

Idempotent (CLAUDE.md rule 5): raw payloads are upserted by (kind, ref_key), activities by garmin_id,
wellness by date. An already-known activity is only re-fetched when its list item changed. Raw payloads are
committed as soon as they arrive, so a crash or Ctrl+C never loses downloaded data; normalization runs from
raw_garmin via training.db.rebuild.
"""

import datetime as dt
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlmodel import Session

from training.db import rebuild, repo
from training.garmin import endpoints as ep
from training.garmin.client import (
    GarminClient,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectNotFoundError,
    GarminConnectTooManyRequestsError,
    RawSink,
)

log = logging.getLogger(__name__)

LAST_ACTIVITY_SYNC = "last_activity_sync"
LAST_WELLNESS_DATE = "last_wellness_date"
PENDING_ACTIVITIES = "pending_activities"
PENDING_WELLNESS = "pending_wellness_days"
ACTIVITY_OVERLAP_DAYS = 2
FIRST_SYNC_DAYS = 14


@dataclass
class SyncResult:
    activities_new: int = 0
    activities_updated: int = 0
    activities_unchanged: int = 0
    activities_pending: int = 0  # incomplete after this run (transient failure) – retried next run
    wellness_days: int = 0
    errors: list[str] = field(default_factory=list)

    def merge(self, other: "SyncResult") -> None:
        self.activities_new += other.activities_new
        self.activities_updated += other.activities_updated
        self.activities_unchanged += other.activities_unchanged
        self.activities_pending += other.activities_pending
        self.wellness_days += other.wellness_days
        self.errors.extend(other.errors)


def raw_sink_for(session: Session) -> RawSink:
    """Raw sink that persists and commits every Garmin response immediately."""

    def sink(kind: str, ref_key: str, payload: Any) -> None:
        repo.store_raw(session, kind, ref_key, payload)
        session.commit()

    return sink


class Ingestor:
    """Fetch → raw_garmin → normalize, shared by sync and backfill.

    Completeness: an activity is put on the `pending_activities` list (sync_state) *before* its endpoints
    are fetched, and its list item – the marker "this version was fully fetched" – is stored only when no
    endpoint failed transiently (404 = permanently absent, fine). A crash, Ctrl+C or exhausted 5xx therefore
    leaves it pending, and every later sync/backfill retries pending work first, regardless of date window.
    Wellness days with transient failures go to `pending_wellness_days` the same way.
    """

    def __init__(self, session: Session, client: GarminClient) -> None:
        self.session = session
        self.client = client
        if client.raw_sink is None:
            client.raw_sink = raw_sink_for(session)

    def _try(self, label: str, fn: Callable[..., Any], *args: Any, errors: list[str]) -> tuple[Any, bool]:
        """Call an endpoint; returns (payload, transient_failure). 404 and bad arguments are permanent."""
        try:
            return fn(*args), False
        except (GarminConnectAuthenticationError, GarminConnectTooManyRequestsError):
            raise  # abort the run; pending markers make it resumable
        except GarminConnectNotFoundError:
            log.info("%s: not found", label)
            return None, False
        except ValueError as exc:
            log.warning("%s failed: %s", label, type(exc).__name__)
            errors.append(f"{label}: {type(exc).__name__}")
            return None, False
        except GarminConnectConnectionError as exc:
            log.warning("%s failed: %s (will retry on the next run)", label, type(exc).__name__)
            errors.append(f"{label}: {type(exc).__name__}")
            return None, True

    # --- pending bookkeeping ------------------------------------------------------------------------------

    def _pending_activities(self) -> dict[str, Any]:
        return repo.get_state_json(self.session, PENDING_ACTIVITIES) or {}

    def _pending_days(self) -> set[str]:
        return set(repo.get_state_json(self.session, PENDING_WELLNESS) or [])

    def _save_pending(self, activities: dict[str, Any] | None = None, days: set[str] | None = None) -> None:
        if activities is not None:
            repo.set_state_json(self.session, PENDING_ACTIVITIES, activities)
        if days is not None:
            repo.set_state_json(self.session, PENDING_WELLNESS, sorted(days))
        self.session.commit()

    # --- activities ----------------------------------------------------------------------------------------

    def activities(self, start: dt.date, end: dt.date) -> SyncResult:
        result = SyncResult()
        for item in self.client.activities_by_date(start, end):
            garmin_id = item.get("activityId")
            if garmin_id is None:
                continue
            unchanged = repo.raw_digest(
                self.session, ep.ACTIVITY_LIST_ITEM, str(garmin_id)
            ) == repo.payload_hash(item)
            if unchanged and repo.activity_id_for(self.session, garmin_id) is not None:
                result.activities_unchanged += 1
                continue
            self._ingest_activity(item, result)
        return result

    def retry_pending(self, result: SyncResult) -> None:
        """Retry activities and wellness days left incomplete by earlier runs."""
        for item in list(self._pending_activities().values()):
            self._ingest_activity(item, result)
        for day in sorted(self._pending_days()):
            self.wellness_day(dt.date.fromisoformat(day), result.errors)

    def _ingest_activity(self, item: dict[str, Any], result: SyncResult) -> None:
        garmin_id = item["activityId"]
        pending = self._pending_activities()
        pending[str(garmin_id)] = item
        self._save_pending(activities=pending)

        known = repo.activity_id_for(self.session, garmin_id) is not None
        label = f"activity {garmin_id}"
        duration = item.get("elapsedDuration") or item.get("duration")
        transient = False
        for part, fn, args in (
            ("summary", self.client.activity_summary, (garmin_id,)),
            ("details", self.client.activity_details, (garmin_id, duration)),
            ("splits", self.client.activity_splits, (garmin_id,)),
            ("hr zones", self.client.activity_hr_zones, (garmin_id,)),
        ):
            transient |= self._try(f"{label} {part}", fn, *args, errors=result.errors)[1]

        if not transient:
            repo.store_raw(self.session, ep.ACTIVITY_LIST_ITEM, str(garmin_id), item)
            pending.pop(str(garmin_id), None)
            self._save_pending(activities=pending)
        try:
            rebuild.rebuild_activity(self.session, garmin_id)
            self.session.commit()
        except LookupError:  # nothing usable fetched yet – stays pending
            self.session.rollback()
        except Exception as exc:  # raw data is already safe; report and continue
            self.session.rollback()
            log.exception("normalizing %s failed", label)
            result.errors.append(f"{label} normalize: {type(exc).__name__}")
        if transient:
            result.activities_pending += 1
        elif known:
            result.activities_updated += 1
        else:
            result.activities_new += 1

    # --- wellness ------------------------------------------------------------------------------------------

    def wellness_day(self, day: dt.date, errors: list[str]) -> bool:
        """Fetch + normalize one day. False if an endpoint failed transiently (the day stays pending)."""
        transient = False
        for kind, fn in (
            (ep.SLEEP, self.client.sleep),
            (ep.USER_SUMMARY, self.client.user_summary),
            (ep.RHR, self.client.rhr),
            (ep.STRESS, self.client.stress),
            (ep.BODY_BATTERY, self.client.body_battery),
        ):
            transient |= self._try(f"{kind} {day}", fn, day, errors=errors)[1]
        try:
            rebuild.rebuild_wellness_day(self.session, day)
            self.session.commit()
        except Exception as exc:
            self.session.rollback()
            log.exception("normalizing wellness %s failed", day)
            errors.append(f"wellness {day} normalize: {type(exc).__name__}")
        days = self._pending_days()
        if transient:
            days.add(day.isoformat())
        else:
            days.discard(day.isoformat())
        self._save_pending(days=days)
        return not transient

    def status(self, day: dt.date, errors: list[str]) -> None:
        """Current Garmin training status / VO2max / lactate threshold – raw only (used from phase 4)."""
        self._try(f"training_status {day}", self.client.training_status, day, errors=errors)
        self._try(f"max_metrics {day}", self.client.max_metrics, day, errors=errors)
        self._try(f"lactate_threshold {day}", self.client.lactate_threshold, day, errors=errors)


def _days(start: dt.date, end: dt.date) -> list[dt.date]:
    return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]


def sync(session: Session, client: GarminClient, today: dt.date) -> SyncResult:
    """Incremental sync up to `today` (local date). Safe to run any number of times."""
    ingest = Ingestor(session, client)
    result = SyncResult()
    ingest.retry_pending(result)
    last_act = repo.get_state_date(session, LAST_ACTIVITY_SYNC)
    last_act = min(last_act, today) if last_act else today - dt.timedelta(days=FIRST_SYNC_DAYS)
    result.merge(ingest.activities(last_act - dt.timedelta(days=ACTIVITY_OVERLAP_DAYS), today))
    repo.set_state(session, LAST_ACTIVITY_SYNC, today.isoformat())
    session.commit()

    last_well = repo.get_state_date(session, LAST_WELLNESS_DATE)
    well_start = min(last_well, today) if last_well else today - dt.timedelta(days=FIRST_SYNC_DAYS)
    for day in _days(well_start, today):
        ingest.wellness_day(day, result.errors)
        result.wellness_days += 1
        repo.set_state(session, LAST_WELLNESS_DATE, day.isoformat())
        session.commit()

    ingest.status(today, result.errors)
    log.info(
        "sync done: %d new, %d updated, %d unchanged, %d pending activities; %d wellness days; %d errors",
        result.activities_new,
        result.activities_updated,
        result.activities_unchanged,
        result.activities_pending,
        result.wellness_days,
        len(result.errors),
    )
    return result
