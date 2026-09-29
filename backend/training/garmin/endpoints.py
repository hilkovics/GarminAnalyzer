"""`raw_garmin.kind` values and their ref_key conventions (PLAN.md §4).

Activity kinds use the Garmin activity id as ref_key, daily kinds the ISO date, range kinds "start..end".
`activity_list_item` and `activity_list` are additions to the PLAN list: the per-item copy is what
incremental sync compares to decide whether an already-known activity changed.
"""

ACTIVITY_LIST = "activity_list"  # ref: "YYYY-MM-DD..YYYY-MM-DD"
ACTIVITY_LIST_ITEM = "activity_list_item"  # ref: garmin id
ACTIVITY_SUMMARY = "activity_summary"  # ref: garmin id
ACTIVITY_DETAILS = "activity_details"  # ref: garmin id
LAPS = "laps"  # ref: garmin id (get_activity_splits)
HR_ZONES = "hr_zones"  # ref: garmin id (get_activity_hr_in_timezones)

SLEEP = "sleep"  # ref: date
RHR = "rhr"  # ref: date
BODY_BATTERY = "body_battery"  # ref: date (get_body_battery(d, d))
STRESS = "stress"  # ref: date
USER_SUMMARY = "user_summary"  # ref: date
TRAINING_STATUS = "training_status"  # ref: date
MAX_METRICS = "max_metrics"  # ref: date
LACTATE_THRESHOLD = "lactate_threshold"  # ref: date fetched ("latest" values as of that day)

ACTIVITY_KINDS = (ACTIVITY_SUMMARY, ACTIVITY_DETAILS, LAPS, HR_ZONES)
WELLNESS_KINDS = (SLEEP, USER_SUMMARY, RHR, STRESS, BODY_BATTERY)
STATUS_KINDS = (TRAINING_STATUS, MAX_METRICS, LACTATE_THRESHOLD)


def date_range_ref(start: object, end: object) -> str:
    return f"{start}..{end}"
