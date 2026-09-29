import pytest
from sqlmodel import Session

from training.db.session import make_engine, migrate


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "training.db"
    migrate(path)
    return path


@pytest.fixture
def engine(db_path):
    eng = make_engine(db_path)
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s
