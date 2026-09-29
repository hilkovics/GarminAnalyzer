"""`sync_state` keys shared by ingestion (garmin/) and the metric pipeline, kept in a neutral module so the
offline pipeline never has to import the Garmin fetch layer."""

LAST_ACTIVITY_SYNC = "last_activity_sync"
LAST_WELLNESS_DATE = "last_wellness_date"
BACKFILL_CURSOR = "backfill_cursor"
PENDING_ACTIVITIES = "pending_activities"  # {garmin_id: {"item": list item, "attempts": n}}
PENDING_WELLNESS = "pending_wellness_days"  # {date: {"attempts": n}}
FAILED_ACTIVITIES = "failed_activities"  # moved here after MAX_ATTEMPTS runs; `sync --retry-failed`
FAILED_WELLNESS = "failed_wellness_days"
# "Metrics needed" markers, written in the same transaction as the typed rows and cleared by
# training.pipeline.update_after_sync – so an interrupted run never leaves rows without metrics.
METRICS_DIRTY_ACTIVITIES = "metrics_dirty_activities"  # [garmin_id, …]
METRICS_DIRTY_WELLNESS = "metrics_dirty_wellness_days"  # [date, …] (RHR feeds TRIMP, METRICS §2.2)
