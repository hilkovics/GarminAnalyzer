"""Incremental sync: activities since last_activity_sync − 2 days, wellness up to today (phase 1).

Idempotent upserts keyed by garmin_id / date; updates sync_state."""
