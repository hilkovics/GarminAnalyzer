"""Commutes – METRICS §2.6: short bike rides count as fatigue, not as training.

A bike activity with moving time (`moving_s`, else `duration_s`) < 1500 s is a commute; the per-activity
`commute_override` (True / False) wins for any sport. `is_commute` is the rule in Python, `commute_expr`
the same rule as a SQL expression over `activity` for queries.
"""

from sqlalchemy import and_, case, func
from sqlalchemy.sql.elements import ColumnElement

from training.db.models import Activity

COMMUTE_MAX_MOVING_S = 1500.0  # §2.6: < 25 min of moving time


def is_commute(
    sport: str | None, moving_s: float | None, duration_s: float | None, override: bool | None
) -> bool:
    """METRICS §2.6 for one activity."""
    if override is not None:
        return bool(override)
    seconds = moving_s if moving_s is not None else duration_s
    return sport == "bike" and seconds is not None and seconds < COMMUTE_MAX_MOVING_S


def activity_is_commute(activity: Activity) -> bool:
    return is_commute(activity.sport, activity.moving_s, activity.duration_s, activity.commute_override)


def commute_expr() -> ColumnElement[bool]:
    """`is_commute` as a SQL boolean over the `activity` columns (never NULL)."""
    seconds = func.coalesce(Activity.moving_s, Activity.duration_s)
    rule = and_(Activity.sport == "bike", seconds.is_not(None), seconds < COMMUTE_MAX_MOVING_S)
    return case(
        (Activity.commute_override.is_(True), True),
        (Activity.commute_override.is_(False), False),
        else_=func.coalesce(rule, False),
    )
