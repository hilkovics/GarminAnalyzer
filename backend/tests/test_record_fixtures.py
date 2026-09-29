"""scripts/record_fixtures.py against a fake client: selection, anonymization, leak guard. No network."""

import inspect
import json
from datetime import date

import pytest
from garminconnect import Garmin

from scripts.record_fixtures import LeakError, record, select_activities, sport_of
from training.garmin.client import GarminConnectNotFoundError

REAL_LAT, REAL_LON = 48.1486, 17.1077


def act(aid: int, key: str, gain: float = 0.0) -> dict:
    return {
        "activityId": aid,
        "activityType": {"typeKey": key},
        "elevationGain": gain,
        "activityName": "Home Town Running",
        "startLatitude": REAL_LAT,
        "startLongitude": REAL_LON,
    }


def test_sport_mapping():
    assert sport_of(act(1, "trail_running")) == "run"
    assert sport_of(act(1, "treadmill_running")) == "run"
    assert sport_of(act(1, "road_biking")) == "bike"
    assert sport_of(act(1, "indoor_cycling")) == "bike"
    assert sport_of(act(1, "virtual_ride")) == "bike"
    assert sport_of(act(1, "strength_training")) == "other"


def test_selection_tops_up_hilly_run_and_bike():
    items = [act(i, "treadmill_running") for i in range(6)] + [act(10, "running", 80), act(11, "cycling")]
    chosen = select_activities(items, 6)
    assert [a["activityId"] for a in chosen] == [0, 1, 2, 3, 4, 5, 10, 11]


def test_selection_does_not_duplicate_when_present():
    items = [act(1, "running", 50), act(2, "road_biking")] + [act(i, "running") for i in range(3, 9)]
    assert len(select_activities(items, 6)) == 6


class FakeApi:
    full_name = "Real Name"
    display_name = "real-display-name"
    profile_id = 98765432


class FakeClient:
    """Records calls and checks each one binds to the real garminconnect.Garmin signature (no guessing)."""

    def __init__(self, extra: dict | None = None) -> None:
        self.api = FakeApi()
        self.calls: list[str] = []
        self.extra = extra or {}

    def call(self, method, *args, **kwargs):
        inspect.signature(getattr(Garmin, method)).bind(None, *args, **kwargs)
        self.calls.append(method)
        if method == "get_activities":
            return [act(111111111, "running", 45), act(222222222, "cycling")]
        if method == "get_activity_details":
            return {
                "activityId": args[0],
                "metricDescriptors": [{"metricsIndex": 0, "key": "directLatitude"}],
                "activityDetailMetrics": [{"metrics": [REAL_LAT]}],
                "geoPolylineDTO": {"minLat": REAL_LAT - 0.01, "maxLon": REAL_LON + 0.01},
            }
        if method == "get_stress_data":
            raise GarminConnectNotFoundError("API Error 404")
        return {"method": method, "ownerFullName": "Real Name", "userId": 98765432, **self.extra}


def test_record_writes_anonymized_files_and_manifest(tmp_path):
    client = FakeClient()
    manifest = record(client, tmp_path, today=date(2026, 9, 29), days=2, offset=(1.0, 1.0))

    assert manifest["has_hilly_run"] and manifest["has_bike"]
    assert "activity_01_running_details.json" in manifest["files"]
    assert "wellness_2026-09-28_sleep.json" in manifest["files"]
    assert {e["method"] for e in manifest["errors"]} == {"get_stress_data"}

    details = json.loads((tmp_path / "activity_01_running_details.json").read_text())
    assert details["activityDetailMetrics"][0]["metrics"] == [pytest.approx(REAL_LAT + 1.0)]
    assert details["geoPolylineDTO"]["minLat"] == pytest.approx(REAL_LAT + 0.99)
    listing = json.loads((tmp_path / "activities_list.json").read_text())
    assert listing[0]["activityName"] == "anonymized"
    assert listing[0]["startLatitude"] == pytest.approx(REAL_LAT + 1.0)
    # fake activity ids are consistent between the list and the per-activity files
    assert details["activityId"] == listing[0]["activityId"] != 111111111

    everything = "".join(p.read_text() for p in tmp_path.glob("*.json"))
    for secret in ("Real Name", "98765432", "111111111", f"{REAL_LAT}"):
        assert secret not in everything
    assert client.calls.count("get_sleep_data") == 2
    assert json.loads((tmp_path / "manifest.json").read_text())["files"] == manifest["files"]


def test_leak_guard_aborts_before_writing(tmp_path):
    client = FakeClient(extra={"unknownGeoField": {"x": REAL_LAT + 0.001, "y": REAL_LON - 0.001}})
    with pytest.raises(LeakError) as err:
        record(client, tmp_path, today=date(2026, 9, 29), days=1, offset=(1.0, 1.0))
    assert "real coordinates" in str(err.value)
    assert str(REAL_LAT)[:5] not in str(err.value)  # the error message itself carries no real value
    offending = str(err.value).split(":")[0]
    assert not (tmp_path / offending).exists()


def test_leak_guard_catches_real_name_under_unknown_key(tmp_path):
    client = FakeClient(extra={"comment": "Great run, Real Name!"})
    with pytest.raises(LeakError, match="real user name/id"):
        record(client, tmp_path, today=date(2026, 9, 29), days=1, offset=(1.0, 1.0))


def test_record_clean_removes_only_fixture_files(tmp_path):
    (tmp_path / "activity_99_old_summary.json").write_text("{}")
    (tmp_path / "keep_me.json").write_text("{}")
    record(FakeClient(), tmp_path, today=date(2026, 9, 29), days=1, offset=(1.0, 1.0))
    assert not (tmp_path / "activity_99_old_summary.json").exists()
    assert (tmp_path / "keep_me.json").exists()
