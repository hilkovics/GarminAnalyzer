"""Diagnostics service (Settings → Diagnostics, `training diagnostics`): sync state and the METRICS §2.5
load sanity check. Returns DiagnosticsDTO only (CLAUDE.md rule 3)."""

import datetime as dt

from sqlalchemy import func, select
from sqlmodel import Session

from training.db import repo
from training.db.models import Activity, ActivityMetric
from training.db.state_keys import (
    BACKFILL_CURSOR,
    FAILED_ACTIVITIES,
    FAILED_WELLNESS,
    LAST_ACTIVITY_SYNC,
    LAST_WELLNESS_DATE,
    PENDING_ACTIVITIES,
    PENDING_WELLNESS,
)
from training.metrics.load import load_sanity
from training.services.dto import DiagnosticsDTO, LoadDivergenceDTO, LoadSanityDTO

DIVERGENCE_PCT = 40.0


def get_diagnostics(session: Session) -> DiagnosticsDTO:
    def state_len(key: str) -> int:
        return len(repo.get_state_json(session, key) or {})

    def state_keys(key: str) -> list[str]:
        return sorted(repo.get_state_json(session, key) or {})

    rows = session.execute(
        select(
            Activity.garmin_id,
            Activity.local_date,
            Activity.sport,
            Activity.garmin_training_load,
            ActivityMetric.load_primary,
            ActivityMetric.hrtss,
            ActivityMetric.rtss,
            ActivityMetric.low_confidence,
            ActivityMetric.threshold_id_used,
        ).join(ActivityMetric, ActivityMetric.activity_id == Activity.id)
    ).all()
    n_activities = session.execute(select(func.count()).select_from(Activity)).scalar_one()

    sanity = load_sanity([r.load_primary for r in rows], [r.garmin_training_load for r in rows])
    divergent = []
    for r in rows:
        if r.hrtss and r.rtss:
            diff = abs(r.hrtss - r.rtss) / min(r.hrtss, r.rtss) * 100
            if diff > DIVERGENCE_PCT:
                divergent.append(
                    LoadDivergenceDTO(
                        garmin_id=r.garmin_id,
                        local_date=r.local_date,
                        sport=r.sport,
                        hrtss=r.hrtss,
                        rtss=r.rtss,
                        diff_pct=round(diff, 1),
                    )
                )
    return DiagnosticsDTO(
        last_activity_sync=repo.get_state_date(session, LAST_ACTIVITY_SYNC),
        last_wellness_date=repo.get_state_date(session, LAST_WELLNESS_DATE),
        backfill_cursor=repo.get_state_date(session, BACKFILL_CURSOR),
        pending_activities=state_len(PENDING_ACTIVITIES),
        pending_wellness_days=state_len(PENDING_WELLNESS),
        failed_activities=[int(k) for k in state_keys(FAILED_ACTIVITIES)],
        failed_wellness_days=[dt.date.fromisoformat(k) for k in state_keys(FAILED_WELLNESS)],
        activities=n_activities,
        activities_with_metrics=len(rows),
        activities_without_threshold=sum(1 for r in rows if r.threshold_id_used is None),
        activities_without_load=sum(1 for r in rows if r.load_primary is None),
        low_confidence_share=(sum(1 for r in rows if r.low_confidence) / len(rows)) if rows else None,
        load_sanity=LoadSanityDTO(r=sanity.r, n=sanity.n, status=sanity.status),
        hrtss_rtss_divergent=sorted(divergent, key=lambda d: -d.diff_pct),
    )
