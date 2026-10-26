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


@pytest.fixture(autouse=True)
def coach_mode(request, monkeypatch):
    """The §10 tests were written for the race-rules coach; since METRICS §11 a day without a race goal uses
    the fitness coach. Tests keep §10 unless marked `@pytest.mark.fitness_coach`."""
    if request.node.get_closest_marker("fitness_coach") is None:
        from training import planning

        monkeypatch.setattr(planning, "mode_for", lambda session, day: "race")


def pytest_configure(config):
    config.addinivalue_line("markers", "fitness_coach: run with the METRICS §11 fitness coach (no race goal)")
