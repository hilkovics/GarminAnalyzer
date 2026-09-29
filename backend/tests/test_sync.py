"""Sync / backfill idempotency and resumability with garminconnect mocked at the client boundary."""

import datetime as dt

import pytest
from sqlalchemy import func, select

from training.db import repo
from training.db.models import Activity, ActivityStream, DailyWellness, RawGarmin
from training.db.rebuild import rebuild_all
from training.garmin.backfill import BACKFILL_CURSOR, backfill
from training.garmin.client import GarminClient, GarminConnectConnectionError, GarminConnectNotFoundError
from training.garmin.sync import sync

TODAY = dt.date(2026, 9, 29)


def _ms(ts: dt.datetime) -> int:
    return int(ts.timestamp() * 1000)


def make_activity(garmin_id: int, day: dt.date, type_key: str = "running", name: str = "Run") -> dict:
    start = dt.datetime.combine(day, dt.time(5, 0), tzinfo=dt.UTC)
    local = start + dt.timedelta(hours=2)
    item = {
        "activityId": garmin_id,
        "activityName": name,
        "startTimeLocal": local.strftime("%Y-%m-%d %H:%M:%S"),
        "startTimeGMT": start.strftime("%Y-%m-%d %H:%M:%S"),
        "activityType": {"typeKey": type_key},
        "eventType": {"typeKey": "uncategorized"},
        "distance": 180.0,
        "duration": 60.0,
        "elapsedDuration": 60.0,
        "movingDuration": 60.0,
        "averageHR": 140.0,
        "maxHR": 150.0,
        "averageSpeed": 3.0,
    }
    summary = {
        "activityId": garmin_id,
        "activityName": name,
        "activityTypeDTO": {"typeKey": type_key},
        "eventTypeDTO": {"typeKey": "uncategorized"},
        "timeZoneUnitDTO": {"timeZone": "Europe/Bratislava"},
        "summaryDTO": {
            "startTimeLocal": local.strftime("%Y-%m-%dT%H:%M:%S.0"),
            "startTimeGMT": start.strftime("%Y-%m-%dT%H:%M:%S.0"),
            "distance": 180.0,
            "duration": 60.0,
            "movingDuration": 60.0,
            "averageHR": 140.0,
            "averageSpeed": 3.0,
        },
    }
    descriptors = ["directTimestamp", "sumDuration", "directHeartRate", "directSpeed", "sumDistance"]
    details = {
        "activityId": garmin_id,
        "metricDescriptors": [{"metricsIndex": i, "key": k} for i, k in enumerate(descriptors)],
        "activityDetailMetrics": [
            {"metrics": [_ms(start) + 1000 * s, float(s), 140.0, 3.0, 3.0 * s]} for s in range(60)
        ],
    }
    return {"item": item, "summary": summary, "details": details}


class FakeGarmin:
    """Minimal garminconnect.Garmin stand-in; counts calls per method."""

    def __init__(self, activities: list[dict]) -> None:
        self.activities = {a["item"]["activityId"]: a for a in activities}
        self.calls: dict[str, int] = {}
        self.fail: dict[str, type[BaseException]] = {}  # method → exception class to raise

    def _hit(self, name: str) -> None:
        self.calls[name] = self.calls.get(name, 0) + 1
        exc = self.fail.get(name)
        if exc is GarminConnectNotFoundError:
            raise exc("API Error 404")
        if exc is not None:
            raise exc("API Error 503") if issubclass(exc, GarminConnectConnectionError) else exc()

    garmin_connect_activities = "/activitylist-service/activities/search/activities"
    page_size: int | None = None  # override to force pagination in tests

    def connectapi(self, path, **kwargs):
        assert path == self.garmin_connect_activities
        self._hit("activity_search")
        params = kwargs["params"]
        lo, hi = dt.date.fromisoformat(params["startDate"]), dt.date.fromisoformat(params["endDate"])
        found = sorted(
            (
                dict(a["item"])
                for a in self.activities.values()
                if lo <= dt.date.fromisoformat(a["item"]["startTimeLocal"][:10]) <= hi
            ),
            key=lambda a: a["startTimeLocal"],
        )
        start, limit = int(params["start"]), self.page_size or int(params["limit"])
        return found[start : start + limit]

    def get_activity(self, activity_id):
        self._hit("get_activity")
        return self.activities[activity_id]["summary"]

    def get_activity_details(self, activity_id, maxchart=2000, maxpoly=4000):
        self._hit("get_activity_details")
        return self.activities[activity_id]["details"]

    def get_activity_splits(self, activity_id):
        self._hit("get_activity_splits")
        return {"activityId": activity_id, "lapDTOs": []}

    def get_activity_hr_in_timezones(self, activity_id):
        self._hit("get_activity_hr_in_timezones")
        return [{"zoneNumber": 2, "secsInZone": 60.0}]

    def get_sleep_data(self, cdate):
        self._hit("get_sleep_data")
        return {"dailySleepDTO": {"calendarDate": cdate, "sleepTimeSeconds": 27000}}

    def get_user_summary(self, cdate):
        self._hit("get_user_summary")
        return {"calendarDate": cdate, "totalSteps": 8000, "restingHeartRate": 48}

    def get_rhr_day(self, cdate):
        self._hit("get_rhr_day")
        return {
            "allMetrics": {
                "metricsMap": {"WELLNESS_RESTING_HEART_RATE": [{"calendarDate": cdate, "value": 48}]}
            }
        }

    def get_stress_data(self, cdate):
        self._hit("get_stress_data")
        return {"calendarDate": cdate, "avgStressLevel": 30}

    def get_body_battery(self, startdate, enddate=None):
        self._hit("get_body_battery")
        return [{"date": startdate, "charged": 50, "drained": 40, "bodyBatteryValuesArray": []}]

    def get_training_status(self, cdate):
        self._hit("get_training_status")
        return {}

    def get_max_metrics(self, cdate):
        self._hit("get_max_metrics")
        return []

    def get_lactate_threshold(self, *, latest=True, start_date=None, end_date=None, aggregation="daily"):
        self._hit("get_lactate_threshold")
        return {}


def client_for(api: FakeGarmin) -> GarminClient:
    return GarminClient(api, rate_limit_s=0, sleep=lambda s: None)


def count(session, model) -> int:
    return session.execute(select(func.count()).select_from(model)).scalar_one()


@pytest.fixture
def api():
    return FakeGarmin(
        [
            make_activity(1001, TODAY - dt.timedelta(days=2)),  # inside the 2-day overlap window
            make_activity(1002, TODAY - dt.timedelta(days=1), "road_biking", "Ride"),
        ]
    )


def test_sync_twice_is_idempotent(session, api):
    first = sync(session, client_for(api), TODAY)
    data = (Activity, ActivityStream, DailyWellness)
    snapshot = {m: count(session, m) for m in data}
    second = sync(session, client_for(api), TODAY)

    assert (first.activities_new, first.errors) == (2, [])
    assert second.activities_new == 0 and second.activities_unchanged == 2
    assert {m: count(session, m) for m in data} == snapshot
    assert snapshot[Activity] == 2 and snapshot[ActivityStream] == 120
    assert api.calls["get_activity_details"] == 2  # unchanged activities are not re-fetched
    assert repo.get_state_date(session, "last_activity_sync") == TODAY

    # the first run had no state (16-day window), later runs use the 2-day overlap: from now on even the
    # raw cache is stable – the same window is only stored once
    raw_before = count(session, RawGarmin)
    sync(session, client_for(api), TODAY)
    assert count(session, RawGarmin) == raw_before
    assert {m: count(session, m) for m in data} == snapshot


def test_changed_list_item_is_refetched(session, api):
    sync(session, client_for(api), TODAY)
    api.activities[1001]["item"]["activityName"] = "Renamed"
    api.activities[1001]["summary"]["activityName"] = "Renamed"
    result = sync(session, client_for(api), TODAY)
    assert result.activities_updated == 1 and result.activities_unchanged == 1
    assert session.execute(select(Activity.name).where(Activity.garmin_id == 1001)).scalar_one() == "Renamed"


def test_backfill_resumes_after_interruption(session):
    days = [dt.date(2026, 7, 10), dt.date(2026, 8, 5), dt.date(2026, 9, 2)]
    api = FakeGarmin([make_activity(2000 + i, d) for i, d in enumerate(days)])

    def interrupt(cursor):
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        backfill(session, client_for(api), 3, TODAY, on_month=interrupt)
    assert repo.get_state_date(session, BACKFILL_CURSOR) == dt.date(2026, 8, 1)
    sleep_calls_after_first_month = api.calls["get_sleep_data"]
    assert sleep_calls_after_first_month == 29  # 1–29 September

    backfill(session, client_for(api), 3, TODAY)
    assert count(session, Activity) == 3
    assert count(session, DailyWellness) == 29 + 31 + 31
    assert api.calls["get_sleep_data"] == 29 + 31 + 31  # finished months were not fetched again
    assert repo.get_state_date(session, BACKFILL_CURSOR) == dt.date(2026, 6, 1)
    assert repo.get_state_date(session, "last_activity_sync") == TODAY

    again = backfill(session, client_for(api), 3, TODAY)  # already complete: no calls
    assert again.wellness_days == 0 and api.calls["get_sleep_data"] == 91
    extended = backfill(session, client_for(api), 4, TODAY)  # one more month further back
    assert extended.wellness_days == 30


def test_rebuild_from_raw_is_offline_and_complete(session, api):
    sync(session, client_for(api), TODAY)
    before = {m: count(session, m) for m in (Activity, ActivityStream, DailyWellness)}
    for model in (ActivityStream, Activity, DailyWellness):
        session.execute(model.__table__.delete())
    session.commit()
    api.fail = dict.fromkeys(api.calls, GarminConnectConnectionError)  # any network access would now raise
    result = rebuild_all(session)
    assert result.errors == []
    assert {m: count(session, m) for m in before} == before


def test_activity_list_is_paged_through_the_rate_limited_client(session, monkeypatch):
    from training.garmin import client as client_mod

    monkeypatch.setattr(client_mod, "ACTIVITY_PAGE_SIZE", 2)
    api = FakeGarmin([make_activity(3000 + i, TODAY - dt.timedelta(days=i % 2)) for i in range(5)])
    stored: list = []
    client = GarminClient(api, rate_limit_s=0, sleep=lambda s: None, raw_sink=lambda *a: stored.append(a))
    items = client.activities_by_date(TODAY - dt.timedelta(days=1), TODAY)
    assert len(items) == 5
    assert api.calls["activity_search"] == 3  # pages of 2, 2, 1 – each one a separate rate-limited call
    assert [k for k, _, _ in stored] == ["activity_list"] and len(stored[0][2]) == 5


def test_backfill_restart_picks_up_old_edits_cheaply(session):
    api = FakeGarmin([make_activity(4001, dt.date(2026, 7, 10)), make_activity(4002, dt.date(2026, 9, 2))])
    backfill(session, client_for(api), 3, TODAY)
    details_before, sleep_before = api.calls["get_activity_details"], api.calls["get_sleep_data"]
    api.activities[4001]["item"]["activityName"] = "Edited in July"
    api.activities[4001]["summary"]["activityName"] = "Edited in July"
    result = backfill(session, client_for(api), 3, TODAY, restart=True)
    assert result.activities_updated == 1 and result.activities_unchanged == 1
    assert api.calls["get_activity_details"] == details_before + 1  # only the edited one
    assert api.calls["get_sleep_data"] == sleep_before  # stored days are not fetched again


def test_backfill_does_not_refetch_empty_days(session):
    """Review round 2, W4: days without data (all endpoints answered, nothing in them) count as known."""

    class EmptyWellness(FakeGarmin):
        def get_sleep_data(self, cdate):
            self._hit("get_sleep_data")
            return {"dailySleepDTO": {"calendarDate": cdate}}

        def get_user_summary(self, cdate):
            self._hit("get_user_summary")
            return {"calendarDate": cdate}

        def get_rhr_day(self, cdate):
            self._hit("get_rhr_day")
            return {}

        def get_stress_data(self, cdate):
            self._hit("get_stress_data")
            return {"calendarDate": cdate, "avgStressLevel": -1}

        def get_body_battery(self, startdate, enddate=None):
            self._hit("get_body_battery")
            return []

    api = EmptyWellness([])
    backfill(session, client_for(api), 2, TODAY)
    assert count(session, DailyWellness) == 0
    calls = api.calls["get_sleep_data"]
    backfill(session, client_for(api), 2, TODAY, restart=True)
    assert api.calls["get_sleep_data"] == calls
