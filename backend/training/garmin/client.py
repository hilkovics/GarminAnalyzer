"""Boundary to the unofficial Garmin Connect client (`garminconnect` ≥ 0.3, native DI tokens).

Everything that talks to Garmin goes through this module, so tests mock it here (CLAUDE.md testing rules).

- Tokens live in `<tokens_dir>/garmin_tokens.json` (written 0600 by garminconnect). The password is only
  held in memory during `login_interactive` and never stored or logged (CLAUDE.md rule 8).
- `GarminClient.call` spaces requests by `rate_limit_s` and retries 429/5xx with exponential backoff
  (CLAUDE.md rule 9). Phase 1 adds one typed method per endpoint and raw_garmin persistence.
"""

import logging
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from garminconnect import (
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectNotFoundError,
    GarminConnectTooManyRequestsError,
)

from training.config import Settings

log = logging.getLogger(__name__)

TOKEN_FILENAME = "garmin_tokens.json"

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

    With `force`, existing tokens are removed first so a fresh credential login always happens.
    Raises GarminConnectAuthenticationError, GarminConnectTooManyRequestsError or
    GarminConnectConnectionError.
    """
    path = token_file(tokens_dir)
    if force and path.exists():
        path.unlink()
    api = Garmin(email=email, password=password, prompt_mfa=prompt_mfa)
    api.login(tokenstore=str(tokens_dir.expanduser()))
    # garminconnect already dumps after a credential login but suppresses errors; dump again so a
    # failure to persist tokens is surfaced instead of silently requiring MFA on every run.
    api.client.dump(str(tokens_dir.expanduser()))
    return api


def connect(tokens_dir: Path) -> Garmin:
    """Resume a session from stored tokens only. Raises GarminConnectAuthenticationError if none/invalid."""
    if not token_file(tokens_dir).exists():
        raise GarminConnectAuthenticationError(f"No Garmin tokens in {tokens_dir}. Run `training login`.")
    api = Garmin()
    api.login(tokenstore=str(tokens_dir.expanduser()))
    return api


def _is_retryable(exc: Exception) -> bool:
    if isinstance(exc, GarminConnectTooManyRequestsError):
        return True
    if isinstance(exc, GarminConnectNotFoundError):
        return False
    if isinstance(exc, GarminConnectConnectionError):
        status = getattr(getattr(exc, "response", None), "status_code", None)
        return status is None or status >= 500
    return False


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
    ) -> None:
        self.api = api
        self.rate_limit_s = rate_limit_s
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self._sleep = sleep
        self._clock = clock
        self._last_call: float | None = None

    @classmethod
    def from_settings(cls, settings: Settings) -> "GarminClient":
        return cls(
            connect(settings.tokens_dir), rate_limit_s=settings.rate_limit_s, max_retries=settings.max_retries
        )

    def _throttle(self) -> None:
        if self._last_call is not None:
            wait = self.rate_limit_s - (self._clock() - self._last_call)
            if wait > 0:
                self._sleep(wait)
        self._last_call = self._clock()

    def call(self, method: str, *args: Any, **kwargs: Any) -> Any:
        """Call `Garmin.<method>(*args, **kwargs)` with spacing and backoff on 429/5xx."""
        fn = getattr(self.api, method)
        for attempt in range(1, self.max_retries + 1):
            self._throttle()
            try:
                return fn(*args, **kwargs)
            except Exception as exc:
                if not _is_retryable(exc) or attempt == self.max_retries:
                    raise
                delay = self.backoff_base_s * 2 ** (attempt - 1)
                log.warning(
                    "Garmin %s failed (%s), retry %d/%d in %.1fs",
                    method,
                    type(exc).__name__,
                    attempt,
                    self.max_retries - 1,
                    delay,
                )
                self._sleep(delay)
        raise AssertionError("unreachable")
