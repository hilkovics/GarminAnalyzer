import copy
import random

import pytest

from training.garmin.anonymize import PLACEHOLDER, anonymize, random_offset

OFFSET = (0.5, -1.0)


def test_plain_coordinate_keys_are_shifted_at_any_depth():
    payload = {
        "startLatitude": 48.1,
        "endLongitude": 17.1,
        "geoPolylineDTO": {"polyline": [{"lat": 48.0, "lon": 17.0, "altitude": 150.0}]},
        "lapDTOs": [{"startLatitude": 48.2, "startLongitude": 17.2, "distance": 1000.0}],
    }
    out = anonymize(payload, OFFSET)
    assert out["startLatitude"] == pytest.approx(48.6)
    assert out["endLongitude"] == pytest.approx(16.1)
    point = out["geoPolylineDTO"]["polyline"][0]
    assert (point["lat"], point["lon"], point["altitude"]) == (
        pytest.approx(48.5),
        pytest.approx(16.0),
        150.0,
    )
    assert out["lapDTOs"][0]["startLatitude"] == pytest.approx(48.7)
    assert out["lapDTOs"][0]["distance"] == 1000.0


def test_detail_metrics_are_shifted_by_descriptor_key_not_position():
    payload = {
        "metricDescriptors": [
            {"metricsIndex": 0, "key": "directHeartRate"},
            {"metricsIndex": 2, "key": "directLatitude"},
            {"metricsIndex": 1, "key": "directLongitude"},
        ],
        "activityDetailMetrics": [{"metrics": [140.0, 17.0, 48.0]}, {"metrics": [141.0, None, None]}],
    }
    out = anonymize(payload, OFFSET)
    assert out["activityDetailMetrics"][0]["metrics"] == [140.0, pytest.approx(16.0), pytest.approx(48.5)]
    assert out["activityDetailMetrics"][1]["metrics"] == [141.0, None, None]


def test_pii_replaced_and_input_not_mutated():
    payload = {
        "ownerDisplayName": "someone",
        "locationName": "Home Town",
        "activityName": "Home Town Running",
        "userProfileId": 12345,
        "activityType": {"typeKey": "running"},
    }
    original = copy.deepcopy(payload)
    out = anonymize(payload, OFFSET)
    assert out["ownerDisplayName"] == PLACEHOLDER
    assert out["locationName"] == PLACEHOLDER
    assert out["activityName"] == PLACEHOLDER
    assert out["userProfileId"] == 0
    assert out["activityType"] == {"typeKey": "running"}
    assert payload == original


def test_non_coordinate_lookalikes_untouched():
    payload = {"latestSpo2": 97, "longestSleep": 3600, "lactateThresholdHeartRate": 170, "isLatest": True}
    assert anonymize(payload, OFFSET) == payload


def test_random_offset_magnitude():
    rng = random.Random(1)
    for _ in range(100):
        dlat, dlon = random_offset(rng)
        assert 0.5 <= abs(dlat) <= 2.0
        assert 0.5 <= abs(dlon) <= 2.0
