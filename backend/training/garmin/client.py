"""Boundary to the unofficial Garmin Connect client (`garminconnect` ≥ 0.3, native DI tokens).

Everything that talks to Garmin goes through this module, so tests mock it here (CLAUDE.md testing rules).

- Tokens live in `<tokens_dir>/garmin_tokens.json` (written 0600 by garminconnect). The password is only
  held in memory during `login_interactive` and never stored or logged (CLAUDE.md rule 8).
- `GarminClient.call` keeps `rate_limit_s` between the end of one request and the start of the next and
  retries 429/5xx and network failures with exponential backoff (CLAUDE.md rule 9). The library's own retry
  layer is disabled (`retry_attempts=0`) so there is exactly one retry policy, and it respects the spacing.
- One method per endpoint. Each response is handed to `raw_sink(kind, ref_key, payload)` *before* it is
  returned, so every Garmin response is persisted verbatim before anything else happens (CLAUDE.md rule 4).

garminconnect 0.3.x raises `GarminConnectConnectionError` *without* a `.response`; the HTTP status is only
in the message ("API Error 503 …", "client error (400)"), so `http_status` parses it from there.
"""

import datetime as dt
import logging
import re
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import requests
from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectNotFoundError,
    GarminConnectTooManyRequestsError,
)

from training.config import Settings
from training.garmin import endpoints as ep

log = logging.getLogger(__name__)

TOKEN_FILENAME = "garmin_tokens.json"
RawSink = Callable[[str, str, Any], None]
MIN_MAXCHART = 2000
_STATUS_RE = re.compile(r"(?:API Error|HTTP|error \()\s*(\d{3})\b")

__all__ = [
    "GarminClient",
    "GarminConnectAuthenticationError",
    "GarminConnectConnectionError",
    "GarminConnectNotFoundError",
    "GarminConnectTooManyRequestsError",
    "connect",
    "login_interactive",
    "token_file",
]


def token_file(tokens_dir: Path) -> Path:
    """Path of the token file inside the token directory (or the path itself if it is a .json file)."""
    tokens_dir = tokens_dir.expanduser()
    return tokens_dir if tokens_dir.suffix == ".json" else tokens_dir / TOKEN_FILENAME


def login_interactive(
    email: str,
    password: str,
    prompt_mfa: Callable[[], str],
    tokens_dir: Path,
    *,
    force: bool = False,
) -> Garmin:
    """Log in with credentials (+ MFA via `prompt_mfa`) and persist tokens to `tokens_dir`.

    With `force`, existing tokens are moved aside so a fresh credential login happens; they are restored if
    the login fails, so a failed `--force` never leaves the user logged out.
    Raises GarminConnectAuthenticationError, GarminConnectTooManyRequestsError,
    GarminConnectConnectionError, or OSError/ValueError if the tokens cannot be written.
    """
    path = token_file(tokens_dir)
    backup = path.with_name(path.name + ".bak")
    if force and path.exists():
        path.replace(backup)
    try:
        api = Garmin(email=email, password=password, prompt_mfa=prompt_mfa, retry_attempts=0)
        api.login(tokenstore=str(tokens_dir.expanduser()))
        # garminconnect already dumps after a credential login but suppresses errors; dump again so a
        # failure to persist tokens is surfaced instead of silently requiring MFA on every run.
        api.client.dump(str(tokens_dir.expanduser()))
    except BaseException:
        if backup.exists():
            backup.replace(path)
        raise
    backup.unlink(missing_ok=True)
    return api


def connect(tokens_dir: Path) -> Garmin:
    """Resume a session from stored tokens only. Raises GarminConnectAuthenticationError if none/invalid."""
    if not token_file(tokens_dir).exists():
        raise GarminConnectAuthenticationError(f"No Garmin tokens in {tokens_dir}. Run `training login`.")
    api = Garmin(retry_attempts=0)
    api.login(tokenstore=str(tokens_dir.expanduser()))
    return api


def http_status(exc: BaseException) -> int | None:
    """HTTP status of a garminconnect error: attribute if present, else parsed from the message."""
    for status in (
        getattr(exc, "status_code", None),
        getattr(getattr(exc, "response", None), "status_code", None),
    ):
        if isinstance(status, int):
            return status
    match = _STATUS_RE.search(str(exc))
    return int(match.group(1)) if match else None


def _has_network_cause(exc: BaseException) -> bool:
    seen: set[int] = set()
    cur: BaseException | None = exc
    while cur is not None and id(cur) not in seen:
        seen.add(id(cur))
        if isinstance(cur, requests.ConnectionError | requests.Timeout):
            return True
        cur = cur.__cause__ or cur.__context__
    return False


def is_retryable(exc: BaseException) -> bool:
    """429, 5xx and genuine network failures are retried; 401, 404, other 4xx and parse errors are not."""
    if isinstance(exc, GarminConnectTooManyRequestsError):
        return True
    if isinstance(exc, GarminConnectAuthenticationError | GarminConnectNotFoundError):
        return False
    if isinstance(exc, GarminConnectConnectionError):
        status = http_status(exc)
        if status is None:
            return _has_network_cause(exc)
        return status == 429 or 500 <= status < 600
    return isinstance(exc, requests.ConnectionError | requests.Timeout)


class GarminClient:
    """Rate-limited, retrying wrapper around a logged-in `Garmin` instance."""

    def __init__(
        self,
        api: Garmin,
        *,
        rate_limit_s: float = 0.7,
        max_retries: int = 5,
        backoff_base_s: float = 2.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        raw_sink: RawSink | None = None,
    ) -> None:
        self.api = api
        self.raw_sink = raw_sink
        self.rate_limit_s = rate_limit_s
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self._sleep = sleep
        self._clock = clock
        self._last_call: float | None = None

    @classmethod
    def from_settings(cls, settings: Settings, raw_sink: RawSink | None = None) -> "GarminClient":
        return cls(
            connect(settings.tokens_dir),
            rate_limit_s=settings.rate_limit_s,
            max_retries=settings.max_retries,
            raw_sink=raw_sink,
        )

    def _throttle(self) -> None:
        if self._last_call is not None:
            wait = self.rate_limit_s - (self._clock() - self._last_call)
            if wait > 0:
                self._sleep(wait)

    def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Call `Garmin.<method>(*args, **kwargs)` with spacing and backoff on 429/5xx."""
        fn = getattr(self.api, method)
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                result = fn(*args, **kwargs)
            except Exception as exc:
                self._last_call = self._clock()
                if not is_retryable(exc) or attempt == self.max_retries:
                    raise
                delay = self.backoff_base_s * 2 ** (attempt - 1)
                log.warning(
                    "Garmin %s failed (%s, status=%s), retry %d/%d in %.1fs",
                    method,
                    type(exc).__name__,
                    http_status(exc),
                    attempt,
                    self.max_retries - 1,
                    delay,
                )
                self._sleep(delay)
                continue
            self._last_call = self._clock()
            return result
        raise AssertionError("unreachable")

    # --- endpoints (every response goes to raw_sink first) -------------------------------------------------

    def _fetch(self, kind: str, ref_key: object, method: str, *args: Any, **kwargs: Any) -> Any:
        payload = self.call(method, *args, **kwargs)
        if self.raw_sink is not None:
            self.raw_sink(kind, str(ref_key), payload)
        return payload

    def activities_by_date(self, start: dt.date, end: dt.date) -> list[dict[str, Any]]:
        """Activity list items with local start date in [start, end], oldest first."""
        payload = self._fetch(
            ep.ACTIVITY_LIST,
            ep.date_range_ref(start, end),
            "get_activities_by_date",
            start.isoformat(),
            end.isoformat(),
            sortorder="asc",
        )
        return list(payload or [])

    def activity_summary(self, garmin_id: int) -> dict[str, Any]:
        return self._fetch(ep.ACTIVITY_SUMMARY, garmin_id, "get_activity", garmin_id)

    def activity_details(self, garmin_id: int, duration_s: float | None = None) -> dict[str, Any]:
        """Detail streams; maxChartSize is sized to the activity so 1 s recordings are not downsampled."""
        maxchart = max(MIN_MAXCHART, int(duration_s or 0) + 100)
        return self._fetch(
            ep.ACTIVITY_DETAILS, garmin_id, "get_activity_details", garmin_id, maxchart=maxchart
        )

    def activity_splits(self, garmin_id: int) -> dict[str, Any]:
        return self._fetch(ep.LAPS, garmin_id, "get_activity_splits", garmin_id)

    def activity_hr_zones(self, garmin_id: int) -> Any:
        return self._fetch(ep.HR_ZONES, garmin_id, "get_activity_hr_in_timezones", garmin_id)

    def sleep(self, day: dt.date) -> dict[str, Any]:
        return self._fetch(ep.SLEEP, day, "get_sleep_data", day.isoformat())

    def rhr(self, day: dt.date) -> dict[str, Any]:
        return self._fetch(ep.RHR, day, "get_rhr_day", day.isoformat())

    def body_battery(self, day: dt.date) -> list[dict[str, Any]]:
        return self._fetch(ep.BODY_BATTERY, day, "get_body_battery", day.isoformat(), day.isoformat())

    def stress(self, day: dt.date) -> dict[str, Any]:
        return self._fetch(ep.STRESS, day, "get_stress_data", day.isoformat())

    def user_summary(self, day: dt.date) -> dict[str, Any]:
        return self._fetch(ep.USER_SUMMARY, day, "get_user_summary", day.isoformat())

    def training_status(self, day: dt.date) -> dict[str, Any]:
        return self._fetch(ep.TRAINING_STATUS, day, "get_training_status", day.isoformat())

    def max_metrics(self, day: dt.date) -> Any:
        return self._fetch(ep.MAX_METRICS, day, "get_max_metrics", day.isoformat())

    def lactate_threshold(self, day: dt.date) -> dict[str, Any]:
        """Garmin's latest LT (HR + speed) as of `day`; stored under that date."""
        return self._fetch(ep.LACTATE_THRESHOLD, day, "get_lactate_threshold", latest=True)
