import copy
import random

import pytest

from training.garmin.anonymize import PLACEHOLDER, IdMap, anonymize, coord_axis, find_leaks, random_offset

OFFSET = (0.5, -1.0)


@pytest.mark.parametrize(
    ("key", "axis"),
    [
        ("lat", 0),
        ("Lat", 0),
        ("latitude", 0),
        ("startLatitude", 0),
        ("minLat", 0),
        ("maxLat", 0),
        ("directLatitude", 0),
        ("start_lat", 0),
        ("lon", 1),
        ("lng", 1),
        ("longitude", 1),
        ("endLongitude", 1),
        ("minLon", 1),
        ("maxLon", 1),
        ("start_lon", 1),
        ("isLatest", None),
        ("flat", None),
        ("latestSpo2", None),
        ("longestSleep", None),
        ("lactateThresholdHeartRate", None),
    ],
)
def test_coord_key_detection(key, axis):
    assert coord_axis(key) == axis


def test_realistic_details_payload_fully_shifted():
    payload = {
        "activityId": 123456789,
        "metricDescriptors": [
            {"metricsIndex": 0, "key": "directHeartRate"},
            {"metricsIndex": 2, "key": "directLatitude"},
            {"metricsIndex": 1, "key": "directLongitude"},
        ],
        "activityDetailMetrics": [{"metrics": [140.0, 17.0, 48.0]}, {"metrics": [141.0, None, None]}],
        "geoPolylineDTO": {
            "startPoint": {"lat": 48.0, "lon": 17.0, "time": 1},
            "endPoint": {"lat": 48.1, "lon": 17.1, "time": 2},
            "minLat": 47.9,
            "maxLat": 48.2,
            "minLon": 16.9,
            "maxLon": 17.2,
            "polyline": [{"lat": 48.0, "lon": 17.0, "altitude": 150.0}],
        },
        "encodedPolyline": "o}~dH_ibhB??",
    }
    out = anonymize(payload, OFFSET)
    assert out["activityDetailMetrics"][0]["metrics"] == [140.0, pytest.approx(16.0), pytest.approx(48.5)]
    assert out["activityDetailMetrics"][1]["metrics"] == [141.0, None, None]
    geo = out["geoPolylineDTO"]
    assert (geo["minLat"], geo["maxLat"]) == (pytest.approx(48.4), pytest.approx(48.7))
    assert (geo["minLon"], geo["maxLon"]) == (pytest.approx(15.9), pytest.approx(16.2))
    assert geo["startPoint"]["lat"] == pytest.approx(48.5)
    assert geo["polyline"][0] == {"lat": pytest.approx(48.5), "lon": pytest.approx(16.0), "altitude": 150.0}
    assert out["encodedPolyline"] == PLACEHOLDER
    assert find_leaks(out, points=[(48.0, 17.0)]) == []


def test_pii_replaced_case_insensitive_and_input_not_mutated():
    payload = {
        "ownerDisplayName": "someone",
        "locationName": "Home Town",
        "activityName": "Home Town Running",
        "description": "ran with Jane",
        "userInfoDto": {
            "displayname": "someone",
            "fullname": "Real Name",
            "profileImageUrlLarge": "https://x",
        },
        "metadataDTO": {"sensors": [{"serialNumber": "3344556677", "sensorType": "HRM"}]},
        "activityType": {"typeKey": "running"},
    }
    original = copy.deepcopy(payload)
    out = anonymize(payload, OFFSET)
    for key in ("ownerDisplayName", "locationName", "activityName", "description"):
        assert out[key] == PLACEHOLDER
    assert set(out["userInfoDto"].values()) == {PLACEHOLDER}
    assert out["metadataDTO"]["sensors"][0] == {"serialNumber": PLACEHOLDER, "sensorType": "HRM"}
    assert out["activityType"] == {"typeKey": "running"}
    assert payload == original


def test_ids_remapped_consistently_across_payloads():
    ids = IdMap()
    summary = anonymize(
        {"activityId": 111111111, "userProfileId": 5555555, "deviceId": 3333333333}, OFFSET, ids
    )
    details = anonymize({"activityId": 111111111, "userId": 5555555}, OFFSET, ids)
    status = anonymize({"latestTrainingStatusData": {"3333333333": {"deviceId": 3333333333}}}, OFFSET, ids)
    assert summary["activityId"] == details["activityId"] != 111111111
    assert summary["userProfileId"] == details["userId"] != 5555555
    fake_device = summary["deviceId"]
    assert status["latestTrainingStatusData"] == {str(fake_device): {"deviceId": fake_device}}


def test_non_coordinate_lookalikes_untouched():
    payload = {"latestSpo2": 97, "longestSleep": 3600, "lactateThresholdHeartRate": 170, "isLatest": True}
    assert anonymize(payload, OFFSET) == payload


def test_find_leaks_detects_unknown_coordinate_keys_and_names():
    leaked = {"weirdGeo": {"a": 48.1234, "b": 17.5678}, "note": "by Real Name"}
    assert find_leaks(leaked, strings=["Real Name"], points=[(48.12, 17.56)]) == [
        "real coordinates present",
        "real user name/id present",
    ]
    # an HR of 48 and a temperature of 17 (integers) are not coordinates; ids need digit boundaries
    assert (
        find_leaks({"hr": 48, "temp": 17, "id": 123456789}, strings=["2345678"], points=[(48.0, 17.0)]) == []
    )


def test_random_offset_magnitude():
    rng = random.Random(1)
    for _ in range(100):
        dlat, dlon = random_offset(rng)
        assert 0.5 <= abs(dlat) <= 2.0
        assert 0.5 <= abs(dlon) <= 2.0
