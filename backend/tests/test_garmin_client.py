"""GarminClient spacing and backoff (CLAUDE.md rule 9) with a fake clock – no network, no real sleeping."""

import pytest

from training.garmin.client import (
    GarminClient,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectNotFoundError,
    GarminConnectTooManyRequestsError,
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


class Response:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code


def conn_error(status: int) -> GarminConnectConnectionError:
    exc = GarminConnectConnectionError(f"HTTP {status}")
    exc.response = Response(status)
    return exc


class FakeApi:
    def __init__(self, failures: list[Exception]) -> None:
        self.failures = list(failures)
        self.calls = 0

    def get_thing(self, x: int) -> dict:
        self.calls += 1
        if self.failures:
            raise self.failures.pop(0)
        return {"x": x}


def make(api: FakeApi, clock: FakeClock, **kw) -> GarminClient:
    return GarminClient(api, rate_limit_s=0.7, sleep=clock.sleep, clock=clock.time, **kw)


def test_calls_are_spaced_by_rate_limit():
    clock = FakeClock()
    client = make(FakeApi([]), clock)
    assert client.call("get_thing", 1) == {"x": 1}
    clock.now += 0.2
    client.call("get_thing", 2)
    assert clock.sleeps == [0.5]


def test_429_and_5xx_retry_with_exponential_backoff():
    clock = FakeClock()
    api = FakeApi([GarminConnectTooManyRequestsError("429"), conn_error(503)])
    client = make(api, clock, backoff_base_s=2.0)
    assert client.call("get_thing", 3) == {"x": 3}
    assert api.calls == 3
    # backoff 2 s, then 4 s; the rate-limit wait is already covered by the backoff
    assert clock.sleeps == [2.0, 4.0]


def test_gives_up_after_max_retries():
    clock = FakeClock()
    api = FakeApi([conn_error(500)] * 10)
    with pytest.raises(GarminConnectConnectionError):
        make(api, clock, max_retries=5).call("get_thing", 1)
    assert api.calls == 5


@pytest.mark.parametrize(
    "exc",
    [
        GarminConnectAuthenticationError("401"),
        GarminConnectNotFoundError("404"),
        conn_error(400),
        ValueError("x"),
    ],
)
def test_non_retryable_errors_fail_fast(exc):
    api = FakeApi([exc])
    with pytest.raises(type(exc)):
        make(api, FakeClock()).call("get_thing", 1)
    assert api.calls == 1
