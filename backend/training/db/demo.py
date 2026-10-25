"""Demo data (`scripts/seed_demo.py`) and its removal from a database that also holds real Garmin data.

Demo rows have no raw Garmin payload behind them, which is what tells them apart from real rows:
- an activity is demo when its garmin_id is in `DEMO_GARMIN_IDS`, its name starts with "Demo " and no raw
  summary / list item exists for that id;
- a wellness day is demo when no raw wellness payload exists for that date (sync and backfill skip days
  that already have a wellness row, so the real day was never fetched – `backfill --restart` fetches it);
- a threshold is demo when it carries exactly the seeded values.
The athlete row is only reported (it may already hold real values entered later).
"""

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy import delete, select, update
from sqlmodel import Session

from training.db import raw_kinds as ep
from training.db.models import Activity, ActivityMetric, Athlete, DailyWellness, RawGarmin, Threshold

DEMO_GARMIN_IDS = range(900_000_000, 901_000_000)
DEMO_NAME_PREFIX = "Demo "
RUN_LTHR, BIKE_LTHR, RUN_THRESHOLD_SPEED = 168.0, 160.0, 1000 / 255  # 4:15 /km
DEMO_ATHLETE = {"sex": "male", "max_hr": 190.0, "birth_year": 1988, "weight_kg": 72.0, "run_bike_split": 0.6}


@dataclass
class DemoRows:
    activity_ids: list[int] = field(default_factory=list)
    wellness_dates: list[dt.date] = field(default_factory=list)
    threshold_ids: list[int] = field(default_factory=list)
    athlete_is_demo: bool = False

    @property
    def empty(self) -> bool:
        return not (self.activity_ids or self.wellness_dates or self.threshold_ids)


def _raw_refs(session: Session, kinds: tuple[str, ...]) -> set[str]:
    return set(session.execute(select(RawGarmin.ref_key).where(RawGarmin.kind.in_(kinds))).scalars())


def _is_demo_threshold(t: Threshold) -> bool:
    if t.sport == "run":
        speed = t.threshold_speed
        return t.lthr == RUN_LTHR and speed is not None and abs(speed - RUN_THRESHOLD_SPEED) < 1e-9
    return t.sport == "bike" and t.lthr == BIKE_LTHR and t.threshold_speed is None


def find_demo_rows(session: Session) -> DemoRows:
    """The demo rows of this database (nothing with a raw Garmin payload behind it)."""
    activity_refs = _raw_refs(session, (ep.ACTIVITY_SUMMARY, ep.ACTIVITY_LIST_ITEM))
    activities = session.execute(
        select(Activity.id, Activity.garmin_id, Activity.name).where(
            Activity.garmin_id >= DEMO_GARMIN_IDS.start, Activity.garmin_id < DEMO_GARMIN_IDS.stop
        )
    ).all()
    activity_ids = [
        a.id
        for a in activities
        if (a.name or "").startswith(DEMO_NAME_PREFIX) and str(a.garmin_id) not in activity_refs
    ]
    wellness_refs = _raw_refs(session, ep.WELLNESS_KINDS)
    days = session.execute(select(DailyWellness.date)).scalars()
    wellness_dates = sorted(d for d in days if d.isoformat() not in wellness_refs)
    thresholds = session.execute(select(Threshold)).scalars()
    athlete = session.execute(select(Athlete)).scalars().first()
    return DemoRows(
        activity_ids=activity_ids,
        wellness_dates=wellness_dates,
        threshold_ids=[t.id for t in thresholds if t.id is not None and _is_demo_threshold(t)],
        athlete_is_demo=athlete is not None
        and all(getattr(athlete, k) == v for k, v in DEMO_ATHLETE.items()),
    )


def purge_demo_rows(session: Session, rows: DemoRows) -> None:
    """Delete the demo activities (streams, metrics and efforts cascade), wellness days and thresholds.

    Metrics computed with a demo threshold lose that link; the caller recomputes afterwards.
    """
    if rows.activity_ids:
        session.execute(delete(Activity).where(Activity.id.in_(rows.activity_ids)))
    if rows.wellness_dates:
        session.execute(delete(DailyWellness).where(DailyWellness.date.in_(rows.wellness_dates)))
    if rows.threshold_ids:
        session.execute(
            update(ActivityMetric)
            .where(ActivityMetric.threshold_id_used.in_(rows.threshold_ids))
            .values(threshold_id_used=None)
        )
        session.execute(delete(Threshold).where(Threshold.id.in_(rows.threshold_ids)))
    session.commit()
