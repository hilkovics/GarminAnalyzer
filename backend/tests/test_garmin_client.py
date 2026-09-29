"""GarminClient spacing and backoff (CLAUDE.md rule 9) with a fake clock – no network, no real sleeping.

Errors are produced by garminconnect's own `_handle_api_errors` decorator (with `retry_attempts=0`, as
GarminClient configures it), so the classifier is tested against exactly what the pinned library raises –
0.3.x attaches no `.response`, the status is only in the message.
"""

import json

import pytest
import requests
from garminconnect import _handle_api_errors

from training.garmin.client import (
    GarminClient,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectNotFoundError,
    GarminConnectTooManyRequestsError,
    http_status,
    is_retryable,
)


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, s: float) -> None:
        self.sleeps.append(round(s, 6))
        self.now += s


def api_error(status: int) -> GarminConnectConnectionError:
    """What garminconnect.client raises for an HTTP error response (before the decorator)."""
    if status == 404:
        return GarminConnectNotFoundError(f"API Error {status}")
    return GarminConnectConnectionError(f"API Error {status} - something")


def as_library_raises(raw: BaseException) -> BaseException:
    """Pass `raw` through garminconnect's real error-translation decorator and return the result."""

    class Obj:
        retry_attempts = 0

    @_handle_api_errors("API call")
    def request(self, path):
        raise raw

    try:
        request(Obj(), "/x")
    except BaseException as exc:
        return exc
    raise AssertionError("decorator swallowed the error")


class FakeApi:
    def __init__(self, failures: list[BaseException], clock: FakeClock | None = None, duration: float = 0.0):
        self.failures = list(failures)
        self.calls = 0
        self.clock = clock
        self.duration = duration

    def get_thing(self, x: int) -> dict:
        self.calls += 1
        if self.clock:
            self.clock.now += self.duration
        if self.failures:
            raise self.failures.pop(0)
        return {"x": x}


def make(api: FakeApi, clock: FakeClock, **kw) -> GarminClient:
    return GarminClient(api, rate_limit_s=0.7, sleep=clock.sleep, clock=clock.time, **kw)


@pytest.mark.parametrize(
    ("raw", "retryable", "status"),
    [
        (api_error(503), True, 503),
        (api_error(500), True, 500),
        (api_error(429), True, 429),
        (api_error(400), False, 400),
        (api_error(403), False, 403),
        (api_error(404), False, 404),
        (api_error(401), False, 401),
        (requests.ConnectionError("reset"), True, None),
        (requests.Timeout("slow"), True, None),
        (json.JSONDecodeError("bad", "doc", 0), False, None),
    ],
)
def test_classifier_on_real_library_errors(raw, retryable, status):
    exc = as_library_raises(raw)
    assert is_retryable(exc) is retryable, (type(exc).__name__, str(exc))
    if status not in (None, 401, 429):  # 401/429 become dedicated exception types
        assert http_status(exc) == status


def test_calls_are_spaced_by_rate_limit_measured_from_end_of_previous_call():
    clock = FakeClock()
    client = make(FakeApi([], clock, duration=1.0), clock)
    assert client.call("get_thing", 1) == {"x": 1}
    clock.now += 0.2
    client.call("get_thing", 2)
    assert clock.sleeps == [0.5]


def test_429_and_5xx_retry_with_exponential_backoff():
    clock = FakeClock()
    failures = [as_library_raises(api_error(429)), as_library_raises(api_error(503))]
    api = FakeApi(failures)
    client = make(api, clock, backoff_base_s=2.0)
    assert client.call("get_thing", 3) == {"x": 3}
    assert api.calls == 3
    # backoff 2 s, then 4 s; the 0.7 s spacing is already covered by the backoff
    assert clock.sleeps == [2.0, 4.0]


def test_gives_up_after_max_retries():
    clock = FakeClock()
    api = FakeApi([as_library_raises(api_error(500)) for _ in range(10)])
    with pytest.raises(GarminConnectConnectionError):
        make(api, clock, max_retries=5).call("get_thing", 1)
    assert api.calls == 5


@pytest.mark.parametrize("status", [400, 401, 403, 404])
def test_client_errors_fail_fast(status):
    exc = as_library_raises(api_error(status))
    api = FakeApi([exc])
    with pytest.raises((GarminConnectConnectionError, GarminConnectAuthenticationError)):
        make(api, FakeClock()).call("get_thing", 1)
    assert api.calls == 1


def test_non_garmin_errors_fail_fast():
    api = FakeApi([ValueError("bad date")])
    with pytest.raises(ValueError):
        make(api, FakeClock()).call("get_thing", 1)
    assert api.calls == 1


def test_library_translates_429_to_dedicated_type():
    assert isinstance(as_library_raises(api_error(429)), GarminConnectTooManyRequestsError)


class SignatureCheckingApi:
    """Accepts any Garmin method, checks the call binds to the real signature, returns a marker payload."""

    garmin_connect_activities = "/activitylist-service/activities/search/activities"

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple, dict]] = []

    def __getattr__(self, name):
        import inspect

        from garminconnect import Garmin

        real = getattr(Garmin, name)

        def method(*args, **kwargs):
            inspect.signature(real).bind(None, *args, **kwargs)
            self.calls.append((name, args, kwargs))
            return {"from": name}

        return method


def test_endpoint_methods_store_raw_before_returning():
    import datetime as dt

    api = SignatureCheckingApi()
    sink: list[tuple[str, str, object]] = []
    returned: list[object] = []

    def raw_sink(kind, ref, payload):
        assert payload not in returned, "raw must be stored before the caller sees the payload"
        sink.append((kind, ref, payload))

    client = GarminClient(api, rate_limit_s=0, sleep=lambda s: None, raw_sink=raw_sink)
    day = dt.date(2026, 9, 20)
    calls = [
        lambda: client.activities_by_date(day, day),
        lambda: client.activity_summary(123),
        lambda: client.activity_details(123, 7200),
        lambda: client.activity_splits(123),
        lambda: client.activity_hr_zones(123),
        lambda: client.sleep(day),
        lambda: client.rhr(day),
        lambda: client.body_battery(day),
        lambda: client.stress(day),
        lambda: client.user_summary(day),
        lambda: client.training_status(day),
        lambda: client.max_metrics(day),
        lambda: client.lactate_threshold(day),
    ]
    for c in calls:
        returned.append(c())
    kinds = [k for k, _, _ in sink]
    assert kinds == [
        "activity_list",
        "activity_summary",
        "activity_details",
        "laps",
        "hr_zones",
        "sleep",
        "rhr",
        "body_battery",
        "stress",
        "user_summary",
        "training_status",
        "max_metrics",
        "lactate_threshold",
    ]
    assert sink[0][1] == "2026-09-20..2026-09-20"
    assert sink[1][1] == "123" and sink[5][1] == "2026-09-20"
    details_call = next(c for c in api.calls if c[0] == "get_activity_details")
    assert details_call[2]["maxchart"] == 7300  # sized to the activity so 1 Hz data is not downsampled
