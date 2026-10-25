"""Phase-8 health DTOs (the automatic morning run); re-exported by `services.dto`.

Timestamps are timezone-aware UTC as written by `training morning`; the UI converts them to local time.
"""

import datetime as dt
from typing import Literal

from pydantic import BaseModel, Field, computed_field


class MorningStepDTO(BaseModel):
    """One step of a `training morning` run."""

    name: Literal["sync", "plan", "push", "telegram"]
    status: Literal["ok", "failed", "skipped"]
    message: str = Field(default="", description="short text, never secrets")
    duration_s: float | None = Field(default=None, description="seconds")


class MorningRunDTO(BaseModel):
    """One stored run of `training morning` (sync_state key `morning_runs`, newest first)."""

    started_at: dt.datetime = Field(description="UTC")
    finished_at: dt.datetime | None = Field(default=None, description="UTC; null when the run did not finish")
    ok: bool
    steps: list[MorningStepDTO] = Field(default_factory=list)

    @computed_field(description="seconds from start to finish; null when unfinished")
    @property
    def duration_s(self) -> float | None:
        if self.finished_at is None:
            return None
        return max(0.0, (self.finished_at - self.started_at).total_seconds())
