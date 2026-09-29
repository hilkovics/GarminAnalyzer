"""Runtime helpers shared by the Streamlit pages: the DB session and "today".

Pages never touch models or SQL – they open a session here and hand it to `training.services.*`.
Tests replace `session` (and `today`) with dummies, so no database is needed to render a page.
"""

import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager

import streamlit as st
from sqlalchemy import Engine
from sqlmodel import Session

from training.config import get_settings
from training.db.session import get_engine, session_scope


@st.cache_resource(show_spinner=False)
def _engine() -> Engine:
    """One engine per Streamlit process (migrates the DB to Alembic head on first use)."""
    return get_engine(get_settings())


@contextmanager
def session() -> Iterator[Session]:
    """Session that commits on success and rolls back on error (see `training.db.session.session_scope`)."""
    with session_scope(_engine()) as s:
        yield s


def today() -> dt.date:
    """The local calendar date the services are asked about."""
    return dt.date.today()
