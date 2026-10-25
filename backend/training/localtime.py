"""The one place that knows the user's local time zone (run times on the Dashboard, diagnostics, run log).

`local_zone()` is the system zone; tests replace it with a fixed `ZoneInfo` instead of changing the process
zone (`time.tzset` does not exist on Windows).
"""

import datetime as dt


def local_zone() -> dt.tzinfo:
    """The system local zone (in Docker: the container's TZ)."""
    zone = dt.datetime.now().astimezone().tzinfo
    return zone if zone is not None else dt.UTC


def to_local(moment: dt.datetime) -> dt.datetime:
    """An aware timestamp in the local zone; a naive one is taken as local already."""
    return moment.astimezone(local_zone()) if moment.tzinfo is not None else moment
