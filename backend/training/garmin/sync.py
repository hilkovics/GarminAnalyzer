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

import requests
from sqlmodel import Session

from training.db import rebuild, repo
from training.db.state_keys import (
    FAILED_ACTIVITIES,
    FAILED_WELLNESS,
    LAST_ACTIVITY_SYNC,
    LAST_WELLNESS_DATE,
    METRICS_DIRTY_ACTIVITIES,
    METRICS_DIRTY_WELLNESS,
    PENDING_ACTIVITIES,
    PENDING_WELLNESS,
)
from training.garmin import endpoints as ep
from training.garmin.client import (
    GarminClient,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectNotFoundError,
    GarminConnectTooManyRequestsError,
    RawSink,
    is_retryable,
)

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
ACTIVITY_OVERLAP_DAYS = 2
FIRST_SYNC_DAYS = 14


@dataclass
class SyncResult:
    activities_new: int = 0
    activities_updated: int = 0
    activities_unchanged: int = 0
    activities_pending: int = 0  # incomplete after this run (transient failure) – retried next run
    activities_failed: int = 0  # gave up after MAX_ATTEMPTS runs – see db-stats / `sync --retry-failed`
    wellness_days: int = 0
    errors: list[str] = field(default_factory=list)
    affected: set[int] = field(default_factory=set)  # garmin ids whose typed rows changed (metrics to redo)

    def merge(self, other: "SyncResult") -> None:
        self.activities_new += other.activities_new
        self.activities_updated += other.activities_updated
        self.activities_unchanged += other.activities_unchanged
        self.activities_pending += other.activities_pending
        self.activities_failed += other.activities_failed
        self.wellness_days += other.wellness_days
        self.errors.extend(other.errors)
        self.affected |= other.affected


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
        self._attempted: set[str] = set()  # activity ids handled in this run
        self._attempted_days: set[str] = set()  # wellness days handled in this run
        if client.raw_sink is None:
            client.raw_sink = raw_sink_for(session)

    def _try(self, label: str, fn: Callable[..., Any], *args: Any, errors: list[str]) -> tuple[Any, bool]:
        """Call an endpoint; returns (payload, transient_failure).

        Transient = worth retrying on a later run (5xx, 429-like, network), decided by `is_retryable`;
        404, other 4xx, parse errors and bad arguments are permanent and never retried.
        """
        try:
            return fn(*args), False
        except (GarminConnectAuthenticationError, GarminConnectTooManyRequestsError):
            raise  # abort the run; pending markers make it resumable
        except GarminConnectNotFoundError:
            log.info("%s: not found", label)
            return None, False
        except (GarminConnectConnectionError, requests.ConnectionError, requests.Timeout, ValueError) as exc:
            transient = is_retryable(exc)
            log.warning(
                "%s failed: %s%s", label, type(exc).__name__, " (retried next run)" if transient else ""
            )
            errors.append(f"{label}: {type(exc).__name__}")
            return None, transient

    # --- pending bookkeeping (sync_state JSON) --------------------------------------------------------------

    def _load(self, key: str) -> dict[str, Any]:
        value = repo.get_state_json(self.session, key)
        return value if isinstance(value, dict) else {}

    def _save(self, key: str, value: dict[str, Any]) -> None:
        repo.set_state_json(self.session, key, value)

    def _record_failure(self, pending_key: str, failed_key: str, ref: str, entry: dict[str, Any]) -> bool:
        """Count one more failed run for `ref`; at MAX_ATTEMPTS move it to the failed list (returns True)."""
        pending = self._load(pending_key)
        entry = {**entry, "attempts": int(pending.get(ref, {}).get("attempts", 0)) + 1}
        if entry["attempts"] >= MAX_ATTEMPTS:
            pending.pop(ref, None)
            failed = self._load(failed_key)
            failed[ref] = entry
            self._save(failed_key, failed)
            log.error("%s failed %d runs in a row – moved to %s", ref, entry["attempts"], failed_key)
            moved = True
        else:
            pending[ref] = entry
            moved = False
        self._save(pending_key, pending)
        return moved

    def _mark_dirty(self, key: str, value: object) -> None:
        dirty = set(repo.get_state_json(self.session, key) or [])
        if value not in dirty:
            dirty.add(value)
            repo.set_state_json(self.session, key, sorted(dirty))

    def _clear(self, pending_key: str, ref: str) -> None:
        pending = self._load(pending_key)
        if pending.pop(ref, None) is not None:
            self._save(pending_key, pending)

    def retry_failed(self) -> int:
        """Move everything from the failed lists back to pending (attempts reset). Returns the count."""
        moved = 0
        for failed_key, pending_key in (
            (FAILED_ACTIVITIES, PENDING_ACTIVITIES),
            (FAILED_WELLNESS, PENDING_WELLNESS),
        ):
            failed, pending = self._load(failed_key), self._load(pending_key)
            for ref, entry in failed.items():
                pending[ref] = {**entry, "attempts": 0}
                moved += 1
            self._save(pending_key, pending)
            self._save(failed_key, {})
        self.session.commit()
        return moved

    # --- activities ----------------------------------------------------------------------------------------

    def activities(self, start: dt.date, end: dt.date) -> SyncResult:
        result = SyncResult()
        failed = self._load(FAILED_ACTIVITIES)
        for item in self.client.activities_by_date(start, end):
            garmin_id = item.get("activityId")
            if garmin_id is None or str(garmin_id) in self._attempted:
                continue
            digest = repo.payload_hash(item)
            gave_up = failed.get(str(garmin_id), {}).get("item")
            if gave_up is not None and repo.payload_hash(gave_up) == digest:
                result.activities_failed += 1  # given up; only retried if it changes or via --retry-failed
                continue
            unchanged = repo.raw_digest(self.session, ep.ACTIVITY_LIST_ITEM, str(garmin_id)) == digest
            if unchanged and repo.activity_id_for(self.session, garmin_id) is not None:
                result.activities_unchanged += 1
                continue
            self._ingest_activity(item, result)
        return result

    def retry_pending(self, result: SyncResult) -> None:
        """Retry activities and wellness days left incomplete by earlier runs (each at most once per run)."""
        for entry in list(self._load(PENDING_ACTIVITIES).values()):
            item = entry.get("item") if isinstance(entry, dict) and "item" in entry else entry
            if isinstance(item, dict) and "activityId" in item:
                self._ingest_activity(item, result)
        for day in sorted(self._load(PENDING_WELLNESS)):
            self.wellness_day(dt.date.fromisoformat(day), result.errors)
            result.wellness_days += 1

    def _ingest_activity(self, item: dict[str, Any], result: SyncResult) -> None:
        garmin_id = item["activityId"]
        ref = str(garmin_id)
        self._attempted.add(ref)
        pending = self._load(PENDING_ACTIVITIES)
        pending[ref] = {"item": item, "attempts": int(pending.get(ref, {}).get("attempts", 0))}
        self._save(PENDING_ACTIVITIES, pending)
        self.session.commit()  # pending *before* any fetch: a crash from here on is retried next run

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

        # Completion marker (list item) + normalized rows + pending removal commit together, so an interrupt
        # during normalization leaves the activity pending instead of "unchanged but stale".
        def finish() -> None:
            if not transient:
                repo.store_raw(self.session, ep.ACTIVITY_LIST_ITEM, ref, item)
                self._clear(PENDING_ACTIVITIES, ref)

        finish()
        try:
            rebuild.rebuild_activity(self.session, garmin_id)
            result.affected.add(garmin_id)
            self._mark_dirty(METRICS_DIRTY_ACTIVITIES, garmin_id)
        except LookupError:  # nothing usable fetched yet
            pass
        except Exception as exc:  # raw data is safe; a normalizer bug is not fixed by re-fetching
            self.session.rollback()
            log.exception("normalizing %s failed", label)
            result.errors.append(f"{label} normalize: {type(exc).__name__}")
            finish()
        failed_now = transient and self._record_failure(
            PENDING_ACTIVITIES, FAILED_ACTIVITIES, ref, {"item": item}
        )
        self.session.commit()
        if failed_now:
            result.activities_failed += 1
        elif transient:
            result.activities_pending += 1
        elif known:
            result.activities_updated += 1
        else:
            result.activities_new += 1

    # --- wellness ------------------------------------------------------------------------------------------

    def wellness_day(self, day: dt.date, errors: list[str]) -> bool:
        """Fetch + normalize one day. False if an endpoint failed transiently (the day stays pending)."""
        ref = day.isoformat()
        if ref in self._attempted_days or ref in self._load(FAILED_WELLNESS):
            return True
        self._attempted_days.add(ref)
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
            if rebuild.rebuild_wellness_day(self.session, day):
                self._mark_dirty(METRICS_DIRTY_WELLNESS, ref)
        except Exception as exc:
            self.session.rollback()
            log.exception("normalizing wellness %s failed", day)
            errors.append(f"wellness {day} normalize: {type(exc).__name__}")
        if transient:
            self._record_failure(PENDING_WELLNESS, FAILED_WELLNESS, ref, {})
        else:
            self._clear(PENDING_WELLNESS, ref)
        self.session.commit()
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
        if day.isoformat() in ingest._attempted_days:  # already retried from pending in this run
            continue
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
