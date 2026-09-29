import copy
import math
import random
from itertools import pairwise

import pytest

from training.garmin.anonymize import (
    PLACEHOLDER,
    IdMap,
    angular_distance_deg,
    anonymize,
    axis_angle_rotation,
    coord_axis,
    find_leaks,
    random_rotation,
    rotate_point,
)

ROT = axis_angle_rotation((1.0, 2.0, 0.5), 40.0)
REAL = (48.1486, 17.1077)


def rot(lat: float, lon: float) -> tuple[float, float]:
    return rotate_point(ROT, lat, lon)


def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    (p1, l1), (p2, l2) = (map(math.radians, a)), (map(math.radians, b))
    h = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin((l2 - l1) / 2) ** 2
    return 2 * 6_371_000 * math.asin(math.sqrt(h))


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


def test_rotation_preserves_distances_and_moves_far_away():
    rng = random.Random(7)
    track = [(REAL[0] + 0.001 * i, REAL[1] + 0.0015 * i) for i in range(50)]
    for _ in range(20):
        r = random_rotation([REAL], rng)
        moved = [rotate_point(r, *p) for p in track]
        assert angular_distance_deg(REAL, moved[0]) >= 10.0
        assert abs(moved[0][0]) <= 55.0 and abs(moved[0][1]) <= 150.0
        for (a, b), (ma, mb) in zip(pairwise(track), pairwise(moved), strict=True):
            assert haversine_m(ma, mb) == pytest.approx(haversine_m(a, b), abs=1e-4)  # 0.1 mm


def test_realistic_details_payload_rotated_as_pairs():
    payload = {
        "activityId": 123456789,
        "metricDescriptors": [
            {"metricsIndex": 0, "key": "directHeartRate"},
            {"metricsIndex": 2, "key": "directLatitude"},
            {"metricsIndex": 1, "key": "directLongitude"},
        ],
        "activityDetailMetrics": [
            {"metrics": [140.0, 17.0, 48.0]},
            {"metrics": [141.0, None, None]},
            {"metrics": [142.0, None, 48.0]},
        ],
        "geoPolylineDTO": {
            "startPoint": {"lat": 48.0, "lon": 17.0, "time": 1},
            "minLat": 47.9,
            "maxLat": 48.2,
            "minLon": 16.9,
            "maxLon": 17.2,
            "polyline": [{"lat": 48.0, "lon": 17.0, "altitude": 150.0, "distanceFromPreviousPoint": 3.2}],
        },
        "encodedPolyline": "o}~dH_ibhB??",
        "startLatitude": 48.0,
        "startLongitude": 17.0,
        "orphanLatitude": 48.0,
    }
    out = anonymize(payload, ROT)
    lat, lon = rot(48.0, 17.0)
    assert out["activityDetailMetrics"][0]["metrics"] == [140.0, pytest.approx(lon), pytest.approx(lat)]
    assert out["activityDetailMetrics"][1]["metrics"] == [141.0, None, None]
    assert out["activityDetailMetrics"][2]["metrics"] == [142.0, None, None]  # unpaired value dropped
    geo = out["geoPolylineDTO"]
    assert (geo["startPoint"]["lat"], geo["startPoint"]["lon"]) == (pytest.approx(lat), pytest.approx(lon))
    assert geo["polyline"][0]["altitude"] == 150.0
    assert geo["polyline"][0]["distanceFromPreviousPoint"] == 3.2
    corners = [rot(47.9, 16.9), rot(48.2, 17.2)]
    assert geo["minLat"] == pytest.approx(min(c[0] for c in corners))
    assert geo["maxLon"] == pytest.approx(max(c[1] for c in corners))
    assert geo["minLat"] <= geo["maxLat"] and geo["minLon"] <= geo["maxLon"]
    assert (out["startLatitude"], out["startLongitude"]) == (pytest.approx(lat), pytest.approx(lon))
    assert out["orphanLatitude"] is None
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
        "metadataDTO": {
            "sensors": [{"serialNumber": 3973543211, "sensorType": "HRM"}, {"serialNumber": "AB12"}]
        },
        "activityType": {"typeKey": "running"},
    }
    original = copy.deepcopy(payload)
    out = anonymize(payload, ROT)
    for key in ("ownerDisplayName", "locationName", "activityName", "description"):
        assert out[key] == PLACEHOLDER
    assert set(out["userInfoDto"].values()) == {PLACEHOLDER}
    assert out["metadataDTO"]["sensors"] == [
        {"serialNumber": PLACEHOLDER, "sensorType": "HRM"},
        {"serialNumber": PLACEHOLDER},
    ]
    assert out["activityType"] == {"typeKey": "running"}
    assert payload == original


def test_ids_remapped_consistently_across_payloads():
    ids = IdMap()
    summary = anonymize({"activityId": 111111111, "userProfileId": 5555555, "deviceId": 3333333333}, ROT, ids)
    details = anonymize({"activityId": 111111111, "userId": 5555555}, ROT, ids)
    status = anonymize({"latestTrainingStatusData": {"3333333333": {"deviceId": 3333333333}}}, ROT, ids)
    multi = anonymize({"parentId": 111111111, "childIds": [111111111, 444444444]}, ROT, ids)
    assert summary["activityId"] == details["activityId"] == multi["parentId"] != 111111111
    assert multi["childIds"][0] == summary["activityId"]
    assert 444444444 not in multi["childIds"]
    assert summary["userProfileId"] == details["userId"] != 5555555
    fake_device = summary["deviceId"]
    assert status["latestTrainingStatusData"] == {str(fake_device): {"deviceId": fake_device}}


def test_non_coordinate_lookalikes_untouched():
    payload = {"latestSpo2": 97, "longestSleep": 3600, "lactateThresholdHeartRate": 170, "isLatest": True}
    assert anonymize(payload, ROT) == payload


def test_find_leaks_reports_key_paths_not_values():
    leaked = {"weirdGeo": {"a": 48.1234, "b": 17.5678}, "notes": [{"text": "by Real Name"}], "uid": 98765432}
    findings = find_leaks(leaked, strings=["Real Name", "98765432"], points=[(48.12, 17.56)])
    assert findings == [
        "real coordinates at $.weirdGeo",
        "real user name/id at $.notes[0].text",
        "real user name/id at $.uid",
    ]
    assert not any("48.1" in f or "Real Name" in f for f in findings)


def test_find_leaks_avoids_substring_and_integer_false_positives():
    payload = {
        "activityType": {"typeKey": "running"},
        "customWorkoutId": 5,
        "hr": 48,
        "temp": 17,
        "n": 123456789,
    }
    # a short display name must not match inside other words or keys; integers are not coordinates
    assert find_leaks(payload, strings=["run", "tom", "2345678"], points=[(48.0, 17.0)]) == []
