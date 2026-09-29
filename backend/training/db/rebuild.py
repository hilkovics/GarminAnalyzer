"""Rebuild typed tables (activity, activity_stream, daily_wellness) from raw_garmin – fully offline.

Sync and backfill use exactly these functions after storing raw payloads, so the typed tables can always
be regenerated from the raw cache (CLAUDE.md rule 4) without touching the network.
"""

import datetime as dt
import logging
from dataclasses import dataclass, field

from sqlmodel import Session

from training.db import repo
from training.garmin import endpoints as ep
from training.normalize.activities import normalize_activity
from training.normalize.streams import normalize_streams
from training.normalize.wellness import normalize_wellness

log = logging.getLogger(__name__)


@dataclass
class RebuildResult:
    activities: int = 0
    stream_rows: int = 0
    wellness_days: int = 0
    errors: list[str] = field(default_factory=list)


def rebuild_activity(session: Session, garmin_id: int) -> tuple[int, int]:
    """Normalize one activity from its raw payloads. Returns (activity id, stream rows written)."""
    ref = str(garmin_id)
    summary = repo.get_raw(session, ep.ACTIVITY_SUMMARY, ref)
    list_item = repo.get_raw(session, ep.ACTIVITY_LIST_ITEM, ref)
    if summary is None and list_item is None:
        raise LookupError(f"no raw summary or list item for activity {garmin_id}")
    row = normalize_activity(summary, list_item)
    activity_id = repo.upsert_activity(session, row)
    details = repo.get_raw(session, ep.ACTIVITY_DETAILS, ref)
    rows = repo.replace_streams(session, activity_id, normalize_streams(details)) if details else 0
    return activity_id, rows


def rebuild_wellness_day(session: Session, day: dt.date) -> None:
    """Normalize one day of wellness from its raw payloads (missing endpoints are fine)."""
    ref = day.isoformat()
    row = normalize_wellness(
        day,
        sleep=repo.get_raw(session, ep.SLEEP, ref),
        user_summary=repo.get_raw(session, ep.USER_SUMMARY, ref),
        rhr=repo.get_raw(session, ep.RHR, ref),
        stress=repo.get_raw(session, ep.STRESS, ref),
        body_battery=repo.get_raw(session, ep.BODY_BATTERY, ref),
    )
    repo.upsert_wellness(session, row)


def rebuild_all(session: Session) -> RebuildResult:
    """Re-normalize every activity and wellness day present in raw_garmin (commits per item)."""
    result = RebuildResult()
    ids = set(repo.raw_ref_keys(session, ep.ACTIVITY_SUMMARY)) | set(
        repo.raw_ref_keys(session, ep.ACTIVITY_LIST_ITEM)
    )
    for ref in sorted(ids, key=int):
        try:
            _, rows = rebuild_activity(session, int(ref))
            session.commit()
            result.activities += 1
            result.stream_rows += rows
        except Exception as exc:  # one broken payload must not stop the rebuild
            session.rollback()
            log.exception("rebuild of activity %s failed", ref)
            result.errors.append(f"activity {ref}: {type(exc).__name__}")
    days = {ref for kind in ep.WELLNESS_KINDS for ref in repo.raw_ref_keys(session, kind)}
    for ref in sorted(days):
        try:
            rebuild_wellness_day(session, dt.date.fromisoformat(ref))
            session.commit()
            result.wellness_days += 1
        except Exception as exc:
            session.rollback()
            log.exception("rebuild of wellness %s failed", ref)
            result.errors.append(f"wellness {ref}: {type(exc).__name__}")
    return result
