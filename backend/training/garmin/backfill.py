"""Resumable history download (PLAN.md phase 1): walks backwards month by month.

The cursor `backfill_cursor` in sync_state is the first day of the next month still to process. It is saved
after every completed month, so an interrupted run continues where it stopped; within a partly done month,
already-known unchanged activities and already-stored wellness days are skipped. Re-running with a larger
`--months` extends the history further back. `restart=True` walks the whole range again from the current
month – cheap for unchanged data (one list call per month) – to pick up activities edited in Garmin Connect
after sync's 2-day overlap. Work left incomplete by transient failures is retried first (see sync.Ingestor).
"""

import datetime as dt
import logging
from collections.abc import Callable

from sqlmodel import Session

from training.db import repo
from training.db.state_keys import BACKFILL_CURSOR
from training.garmin import endpoints as ep
from training.garmin.client import GarminClient
from training.garmin.sync import (
    LAST_ACTIVITY_SYNC,
    LAST_WELLNESS_DATE,
    PENDING_WELLNESS,
    Ingestor,
    SyncResult,
)

log = logging.getLogger(__name__)


def month_start(day: dt.date) -> dt.date:
    return day.replace(day=1)


def add_months(first_of_month: dt.date, months: int) -> dt.date:
    index = first_of_month.year * 12 + first_of_month.month - 1 + months
    return dt.date(index // 12, index % 12 + 1, 1)


def month_end(first_of_month: dt.date) -> dt.date:
    return add_months(first_of_month, 1) - dt.timedelta(days=1)


def _known_wellness_days(session: Session, start: dt.date, end: dt.date) -> set[dt.date]:
    """Days that need no fetch: a wellness row exists, or every endpoint answered (raw stored) and the day is
    not pending – i.e. a day that simply has no data. Days whose endpoints 404 are fetched again."""
    known = repo.wellness_dates(session, start, end)
    lo, hi = start.isoformat(), end.isoformat()
    answered = [{r for r in repo.raw_ref_keys(session, kind) if lo <= r <= hi} for kind in ep.WELLNESS_KINDS]
    pending = set(repo.get_state_json(session, PENDING_WELLNESS) or {})
    complete = set.intersection(*answered) - pending if answered else set()
    return known | {dt.date.fromisoformat(r) for r in complete}


def backfill(
    session: Session,
    client: GarminClient,
    months: int,
    today: dt.date,
    *,
    restart: bool = False,
    on_month: Callable[[dt.date], None] | None = None,
) -> SyncResult:
    """Download `months` calendar months (including the current one) of activities and wellness."""
    if months < 1:
        raise ValueError("months must be ≥ 1")
    ingest = Ingestor(session, client)
    target = add_months(month_start(today), -(months - 1))
    stored = repo.get_state_date(session, BACKFILL_CURSOR)
    cursor = month_start(today) if restart or stored is None else stored
    result = SyncResult()
    ingest.retry_pending(result)
    if cursor < target:
        log.info("backfill already complete back to %s", target)
    while cursor >= target:
        end = min(month_end(cursor), today)
        log.info("backfill %s … %s", cursor, end)
        month = ingest.activities(cursor, end)
        known_days = _known_wellness_days(session, cursor, end)
        day = cursor
        while day <= end:
            if day not in known_days:
                ingest.wellness_day(day, month.errors)
                month.wellness_days += 1
            day += dt.timedelta(days=1)
        result.merge(month)
        cursor = add_months(cursor, -1)
        repo.set_state(session, BACKFILL_CURSOR, cursor.isoformat())
        session.commit()
        if on_month is not None:
            on_month(cursor)

    # hand over to incremental sync
    for key in (LAST_ACTIVITY_SYNC, LAST_WELLNESS_DATE):
        if repo.get_state(session, key) is None:
            repo.set_state(session, key, today.isoformat())
    session.commit()
    return result
