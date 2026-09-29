"""Garmin endpoint helpers. The `raw_garmin.kind` constants live in `training.db.raw_kinds` (neutral module)
and are re-exported here for the fetch layer."""

from training.db.raw_kinds import (
    ACTIVITY_DETAILS,
    ACTIVITY_KINDS,
    ACTIVITY_LIST,
    ACTIVITY_LIST_ITEM,
    ACTIVITY_SUMMARY,
    BODY_BATTERY,
    HR_ZONES,
    LACTATE_THRESHOLD,
    LAPS,
    MAX_METRICS,
    RHR,
    SLEEP,
    STATUS_KINDS,
    STRESS,
    TRAINING_STATUS,
    USER_SUMMARY,
    WELLNESS_KINDS,
)

__all__ = [
    "ACTIVITY_DETAILS",
    "ACTIVITY_KINDS",
    "ACTIVITY_LIST",
    "ACTIVITY_LIST_ITEM",
    "ACTIVITY_SUMMARY",
    "BODY_BATTERY",
    "HR_ZONES",
    "LACTATE_THRESHOLD",
    "LAPS",
    "MAX_METRICS",
    "RHR",
    "SLEEP",
    "STATUS_KINDS",
    "STRESS",
    "TRAINING_STATUS",
    "USER_SUMMARY",
    "WELLNESS_KINDS",
    "date_range_ref",
]


def date_range_ref(start: object, end: object) -> str:
    return f"{start}..{end}"
