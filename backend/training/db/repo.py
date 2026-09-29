"""Idempotent upsert and query helpers over the SQLModel tables (CLAUDE.md rule 5).

All writes are keyed by natural keys (raw: kind + ref_key, activity: garmin_id, wellness: date), so running
sync or backfill twice never duplicates rows.
"""

import datetime as dt
import hashlib
import json
import math
from typing import Any

import pandas as pd
from sqlalchemy import delete, func, insert, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlmodel import Session, SQLModel

from training.db.models import Activity, ActivityStream, DailyWellness, RawGarmin, SyncState, utcnow


def payload_hash(payload: Any) -> str:
    """Stable SHA-256 of a JSON payload (key order independent)."""
    blob = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


# --- raw_garmin --------------------------------------------------------------------------------------------


def store_raw(session: Session, kind: str, ref_key: str, payload: Any) -> bool:
    """Upsert a verbatim Garmin response. Returns True if it is new or its content changed."""
    digest = payload_hash(payload)
    existing = session.exec(
        select(RawGarmin.payload_sha256).where(RawGarmin.kind == kind, RawGarmin.ref_key == ref_key)
    ).first()
    old_digest = existing[0] if existing is not None else None
    stmt = sqlite_insert(RawGarmin.__table__).values(
        kind=kind, ref_key=ref_key, fetched_at=utcnow(), payload_sha256=digest, payload=payload
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["kind", "ref_key"],
        set_={
            "fetched_at": stmt.excluded.fetched_at,
            "payload_sha256": digest,
            "payload": stmt.excluded.payload,
        },
    )
    session.execute(stmt)
    return old_digest != digest


def get_raw(session: Session, kind: str, ref_key: str) -> Any | None:
    row = session.exec(
        select(RawGarmin.payload).where(RawGarmin.kind == kind, RawGarmin.ref_key == ref_key)
    ).first()
    return row[0] if row is not None else None


def raw_ref_keys(session: Session, kind: str) -> list[str]:
    return list(session.exec(select(RawGarmin.ref_key).where(RawGarmin.kind == kind)).scalars())


# --- activities ---------------------------------------------------------------------------------------------


def _upsert(session: Session, model: type[SQLModel], row: dict[str, Any], key: str) -> None:
    stmt = sqlite_insert(model.__table__).values(**row)
    updates = {c: stmt.excluded[c] for c in row if c != key}
    session.execute(stmt.on_conflict_do_update(index_elements=[key], set_=updates))


def upsert_activity(session: Session, row: dict[str, Any]) -> int:
    """Insert or update an activity by garmin_id; returns the internal activity id."""
    _upsert(session, Activity, row, "garmin_id")
    activity_id = activity_id_for(session, row["garmin_id"])
    assert activity_id is not None
    return activity_id


def activity_id_for(session: Session, garmin_id: int) -> int | None:
    row = session.exec(select(Activity.id).where(Activity.garmin_id == garmin_id)).first()
    return row[0] if row is not None else None


def _clean(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if hasattr(value, "item"):  # numpy scalar
        return _clean(value.item())
    return value


def replace_streams(session: Session, activity_id: int, streams: pd.DataFrame) -> int:
    """Replace all stream rows of an activity (1 Hz); NaN → NULL. Returns the number of rows written."""
    session.execute(
        delete(ActivityStream.__table__).where(ActivityStream.__table__.c.activity_id == activity_id)
    )
    if streams.empty:
        return 0
    columns = [c.name for c in ActivityStream.__table__.columns if c.name != "activity_id"]
    frame = streams.reindex(columns=columns)
    records = [
        {"activity_id": activity_id, **{c: _clean(v) for c, v in zip(columns, values, strict=True)}}
        for values in frame.itertuples(index=False, name=None)
    ]
    for r in records:
        r["moving"] = bool(r["moving"]) if r["moving"] is not None else True
    session.execute(insert(ActivityStream.__table__), records)
    return len(records)


# --- wellness -----------------------------------------------------------------------------------------------


def upsert_wellness(session: Session, row: dict[str, Any]) -> None:
    _upsert(session, DailyWellness, {k: _clean(v) for k, v in row.items()}, "date")


def wellness_dates(session: Session, start: dt.date, end: dt.date) -> set[dt.date]:
    rows = session.exec(
        select(DailyWellness.date).where(DailyWellness.date >= start, DailyWellness.date <= end)
    )
    return set(rows.scalars())


# --- sync_state ---------------------------------------------------------------------------------------------


def get_state(session: Session, key: str) -> str | None:
    row = session.exec(select(SyncState.value).where(SyncState.key == key)).first()
    return row[0] if row is not None else None


def set_state(session: Session, key: str, value: str) -> None:
    _upsert(session, SyncState, {"key": key, "value": value}, "key")


def get_state_date(session: Session, key: str) -> dt.date | None:
    value = get_state(session, key)
    return dt.date.fromisoformat(value) if value else None


# --- stats --------------------------------------------------------------------------------------------------


def table_counts(session: Session) -> dict[str, int]:
    """Row count per table (sorted by table name)."""
    counts = {}
    for name, table in sorted(SQLModel.metadata.tables.items()):
        counts[name] = session.execute(select(func.count()).select_from(table)).scalar_one()
    return counts


def raw_counts_by_kind(session: Session) -> dict[str, int]:
    rows = session.execute(
        select(RawGarmin.kind, func.count()).group_by(RawGarmin.kind).order_by(RawGarmin.kind)
    )
    return {kind: n for kind, n in rows}
