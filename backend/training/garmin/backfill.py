"""Resumable history download (PLAN.md phase 1): walks backwards month by month.

The cursor `backfill_cursor` in sync_state is the first day of the next month still to process. It is saved
after every completed month, so an interrupted run continues where it stopped; within a partly done month,
already-known unchanged activities and already-stored wellness days are skipped. Re-running with a larger
`--months` extends the history further back.
"""

import datetime as dt
import logging
from collections.abc import Callable

from sqlmodel import Session

from training.db import repo
from training.garmin.client import GarminClient
from training.garmin.sync import LAST_ACTIVITY_SYNC, LAST_WELLNESS_DATE, Ingestor, SyncResult

log = logging.getLogger(__name__)

BACKFILL_CURSOR = "backfill_cursor"


def month_start(day: dt.date) -> dt.date:
    return day.replace(day=1)


def add_months(first_of_month: dt.date, months: int) -> dt.date:
    index = first_of_month.year * 12 + first_of_month.month - 1 + months
    return dt.date(index // 12, index % 12 + 1, 1)


def month_end(first_of_month: dt.date) -> dt.date:
    return add_months(first_of_month, 1) - dt.timedelta(days=1)


def backfill(
    session: Session,
    client: GarminClient,
    months: int,
    today: dt.date,
    *,
    on_month: Callable[[dt.date], None] | None = None,
) -> SyncResult:
    """Download `months` calendar months (including the current one) of activities and wellness."""
    if months < 1:
        raise ValueError("months must be ≥ 1")
    ingest = Ingestor(session, client)
    target = add_months(month_start(today), -(months - 1))
    stored = repo.get_state_date(session, BACKFILL_CURSOR)
    cursor = stored if stored is not None else month_start(today)
    result = SyncResult()
    if cursor < target:
        log.info("backfill already complete back to %s", target)
    while cursor >= target:
        end = min(month_end(cursor), today)
        log.info("backfill %s … %s", cursor, end)
        month = ingest.activities(cursor, end)
        known_days = repo.wellness_dates(session, cursor, end)
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
