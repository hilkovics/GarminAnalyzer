"""FastAPI dependencies: DB session, `today` and settings. Tests override each through
`app.dependency_overrides[deps.get_session]` etc."""

import datetime as dt
import threading
from collections.abc import Iterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import Engine
from sqlmodel import Session

from training.config import Settings, get_settings
from training.db.session import get_engine

_ENGINE_LOCK = threading.Lock()


@lru_cache
def _cached_engine() -> Engine:
    return get_engine(get_settings())


def _engine() -> Engine:
    """The engine of the configured database (migrated to head), created once on first use and shared –
    also when the first requests arrive in parallel (the React app loads several endpoints at once)."""
    with _ENGINE_LOCK:
        return _cached_engine()


def get_session() -> Iterator[Session]:
    with Session(_engine()) as session:
        yield session


def get_today() -> dt.date:
    return dt.date.today()


def get_config() -> Settings:
    return get_settings()


SessionDep = Annotated[Session, Depends(get_session)]
TodayDep = Annotated[dt.date, Depends(get_today)]
ConfigDep = Annotated[Settings, Depends(get_config)]
