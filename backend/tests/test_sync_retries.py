"""Sync retry semantics: transient vs permanent failures, pending/failed queues, interruptions.

Split from test_sync.py (file size); shares its FakeGarmin fixtures.
"""

import datetime as dt

import pytest
from sqlalchemy import select

from training.db import repo
from training.db.models import Activity, ActivityStream, DailyWellness
from training.garmin.client import GarminClient, GarminConnectConnectionError, GarminConnectNotFoundError
from training.garmin.sync import sync

from .test_sync import TODAY, FakeGarmin, client_for, count, make_activity


@pytest.fixture
def api():
    return FakeGarmin(
        [
            make_activity(1001, TODAY - dt.timedelta(days=2)),
            make_activity(1002, TODAY - dt.timedelta(days=1), "road_biking", "Ride"),
        ]
    )


def test_404_is_permanent_and_not_an_error(session, api):
    api.fail = {"get_activity_hr_in_timezones": GarminConnectNotFoundError}
    result = sync(session, client_for(api), TODAY)
    assert (result.activities_new, result.activities_pending, result.errors) == (2, 0, [])
    assert repo.get_state_json(session, "pending_activities") in (None, {})


def test_transient_failure_leaves_activity_pending_and_it_is_retried(session, api):
    """Review phase 1, blocker 1 (a): a failed details fetch must not be marked done."""
    api.fail = {"get_activity_details": GarminConnectConnectionError}
    first = sync(session, client_for(api), TODAY)
    assert first.activities_pending == 2 and any("details" in e for e in first.errors)
    assert count(session, Activity) == 2 and count(session, ActivityStream) == 0  # rows from summaries
    assert set(repo.get_state_json(session, "pending_activities")) == {"1001", "1002"}

    api.fail = {}
    second = sync(session, client_for(api), TODAY)
    assert second.activities_updated == 2 and second.activities_pending == 0
    assert count(session, ActivityStream) == 120
    assert repo.get_state_json(session, "pending_activities") == {}


def test_pending_activity_is_retried_even_outside_the_sync_window(session, api):
    api.fail = {"get_activity_details": GarminConnectConnectionError}
    sync(session, client_for(api), TODAY)
    api.fail = {}
    later = TODAY + dt.timedelta(days=30)  # the activities are far outside the 2-day overlap now
    sync(session, client_for(api), later)
    assert count(session, ActivityStream) == 120


def test_interrupted_refetch_of_a_changed_activity_resumes(session, api):
    """Review phase 1, blocker 1 (b): Ctrl+C during the refetch must not consume the change signal."""
    sync(session, client_for(api), TODAY)
    api.activities[1001]["item"]["activityName"] = "Renamed"
    api.activities[1001]["summary"]["activityName"] = "Renamed"
    api.fail = {"get_activity": KeyboardInterrupt}
    with pytest.raises(KeyboardInterrupt):
        sync(session, client_for(api), TODAY)
    api.fail = {}
    sync(session, client_for(api), TODAY)
    assert session.execute(select(Activity.name).where(Activity.garmin_id == 1001)).scalar_one() == "Renamed"


def test_failed_wellness_day_is_not_written_and_retried(session, api):
    """Review phase 1, blocker 2: no all-NULL rows; transient failures are retried."""
    api.fail = {m: GarminConnectConnectionError for m in ("get_sleep_data", "get_user_summary", "get_rhr_day",
                                                          "get_stress_data", "get_body_battery")}  # fmt: skip
    sync(session, client_for(api), TODAY)
    assert count(session, DailyWellness) == 0
    assert len(repo.get_state_json(session, "pending_wellness_days")) == 15
    api.fail = {}
    sync(session, client_for(api), TODAY)
    assert count(session, DailyWellness) == 15
    assert repo.get_state_json(session, "pending_wellness_days") == {}


def test_non_retryable_4xx_is_permanent(session, api):
    """Review round 2, W2: a 403 must not keep an activity pending forever."""

    class Forbidden(GarminConnectConnectionError):
        pass

    def forbidden(*a, **k):
        raise Forbidden("API call client error (403): API Error 403")

    api.get_activity = forbidden
    result = sync(session, client_for(api), TODAY)
    assert result.activities_pending == 0 and any("summary" in e for e in result.errors)
    assert repo.get_state_json(session, "pending_activities") == {}


def test_interrupt_during_normalization_keeps_update_pending(session, api, monkeypatch):
    """Review round 2, W1: Ctrl+C inside rebuild must not leave an updated activity stale."""
    from training.db import rebuild

    sync(session, client_for(api), TODAY)
    api.activities[1001]["item"]["activityName"] = "Renamed"
    api.activities[1001]["summary"]["activityName"] = "Renamed"
    real = rebuild.rebuild_activity

    def interrupted(*a, **k):
        raise KeyboardInterrupt

    monkeypatch.setattr(rebuild, "rebuild_activity", interrupted)
    with pytest.raises(KeyboardInterrupt):
        sync(session, client_for(api), TODAY)
    session.rollback()
    monkeypatch.setattr(rebuild, "rebuild_activity", real)
    sync(session, client_for(api), TODAY)
    assert session.execute(select(Activity.name).where(Activity.garmin_id == 1001)).scalar_one() == "Renamed"


def test_persistent_failure_moves_to_failed_after_max_attempts(session, api):
    """Review round 2, W3: bounded retries, and nothing is fetched twice in one run."""
    from training.garmin.sync import MAX_ATTEMPTS, Ingestor

    api.fail = {"get_activity_details": GarminConnectConnectionError}
    client = GarminClient(api, rate_limit_s=0, sleep=lambda s: None, max_retries=1)
    sync(session, client, TODAY)
    assert api.calls["get_activity_details"] == 2  # two activities, once each
    for _ in range(MAX_ATTEMPTS - 1):
        before = api.calls["get_activity_details"]
        sync(session, client, TODAY)  # both are pending *and* inside the window
        assert api.calls["get_activity_details"] - before == 2  # still once each per run
    assert repo.get_state_json(session, "pending_activities") == {}
    assert set(repo.get_state_json(session, "failed_activities")) == {"1001", "1002"}
    before = api.calls["get_activity_details"]
    sync(session, client, TODAY)
    assert api.calls["get_activity_details"] == before  # given up: no more automatic retries

    api.fail = {}
    assert Ingestor(session, client).retry_failed() == 2
    sync(session, client, TODAY)
    assert count(session, ActivityStream) == 120 and repo.get_state_json(session, "failed_activities") == {}
