"""Health page service and API (METRICS §12) on the wellness-seeded DB (107 days, sleep / RHR / BB / load)."""

import datetime as dt

import pytest
from sqlmodel import Session

from training.analysis import health as h
from training.db import repo
from training.db.session import make_engine
from training.pipeline_wellness import health_frame
from training.services import health as svc
from training.services.errors import InvalidInputError

from .seeding import TODAY, make_client
from .wellness_seeding import FIRST_DAY, wellness_db


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(wellness_db(tmp_path))
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


def test_frame_is_a_full_calendar_with_every_metric(session):
    frame = health_frame(session, TODAY)
    assert list(frame.columns) == [m.key for m in h.METRICS]
    assert frame.index[0] == FIRST_DAY and frame.index[-1] == TODAY
    assert len(frame) == (TODAY - FIRST_DAY).days + 1
    assert frame["sleep_s"].notna().all() and frame["load"].notna().any()
    assert frame["respiration_sleep"].isna().all()  # not seeded


def test_overview(session):
    dto = svc.get_overview(session, TODAY)
    assert dto.first_date == FIRST_DAY and [m.key for m in dto.metrics] == [m.key for m in h.METRICS]
    sleep = next(m for m in dto.metrics if m.key == "sleep_s")
    assert sleep.latest_date == TODAY and sleep.mean7 is not None and sleep.median28 is not None
    assert sleep.change.recent is not None and [x.month for x in sleep.monthly] == [
        "2026-06",
        "2026-07",
        "2026-08",
        "2026-09",
    ]
    empty = next(m for m in dto.metrics if m.key == "respiration_sleep")
    assert (empty.latest, empty.mean7, empty.monthly, empty.change.notable) == (None, None, [], False)


def test_series_and_validation(session):
    [rhr, sleep] = svc.get_series(session, ["rhr", "sleep_s"], days=30, today=TODAY)
    assert len(rhr.points) == 30 and rhr.points[-1].date == TODAY and rhr.unit == "bpm"
    assert sleep.points[-1].median28 is not None
    for bad in (["nope"], [], ["rhr"] * 5):
        with pytest.raises(InvalidInputError):
            svc.get_series(session, bad, days=30, today=TODAY)
    with pytest.raises(InvalidInputError):
        svc.get_series(session, ["rhr"], days=3, today=TODAY)


def test_relationships_find_a_planted_effect(session):
    # plant: high daily stress → less sleep the next night
    import numpy as np

    rng = np.random.default_rng(5)
    frame = health_frame(session, TODAY)
    for day in frame.index[:-1]:
        stress = float(30 + rng.normal(0, 8))
        repo.upsert_wellness(session, {"date": day, "stress_avg": stress})
        nxt = day + dt.timedelta(days=1)
        repo.upsert_wellness(session, {"date": nxt, "sleep_s": 7.5 * 3600 - 400 * (stress - 30)})
    session.commit()
    dto = svc.get_relationships(session, TODAY)
    assert dto.tested > 0 and dto.findings
    top = dto.findings[0]
    assert (top.x, top.y, top.lag) == ("stress_avg", "sleep_s", 1) and top.rho < -0.8
    assert top.text.startswith(
        "Keď je „Denný stres“ nad tvojím normálom, „Spánok“ býva v nasledujúci deň skôr pod"
    )
    assert "silná súvislosť (ρ = −1,00, n = 100)." in top.text and len(dto.others) <= svc.MAX_OTHERS


def test_api(engine):
    client = make_client(engine)
    assert client.get("/api/wellness/health").status_code == 200
    body = client.get("/api/wellness/health/series", params={"metrics": "rhr,sleep_s", "days": 14}).json()
    assert [s["key"] for s in body] == ["rhr", "sleep_s"] and len(body[0]["points"]) == 14
    assert client.get("/api/wellness/health/series", params={"metrics": "x"}).status_code == 422
    rel = client.get("/api/wellness/health/relationships").json()
    assert {"tested", "findings", "others"} <= set(rel)


def test_frame_stops_at_today_and_days_boundary(session):
    from training.db.models import DailyLoad

    session.add(DailyLoad(date=TODAY + dt.timedelta(days=3), load_total=50.0))
    session.commit()
    assert health_frame(session, TODAY).index[-1] == TODAY
    assert len(svc.get_series(session, ["rhr"], days=7, today=TODAY)[0].points) == 7
    with pytest.raises(InvalidInputError):
        svc.get_series(session, ["rhr"], days=6, today=TODAY)


@pytest.mark.parametrize(
    ("rho", "word", "side"),
    [(0.29, "slabá", "nad"), (0.3, "stredná", "nad"), (-0.49, "stredná", "pod"), (0.5, "silná", "nad")],
)
def test_sentence_strength_and_side(rho, word, side):
    r = h.Relationship("rhr", "sleep_s", 0, 40, rho, rho - 0.1, rho + 0.1, 0.01, True)
    text = svc.sentence(r)
    assert f"skôr {side} normálom – {word} súvislosť" in text and "v ten istý deň" in text


def test_missing_history_is_flagged(session):
    repo.upsert_wellness(session, {"date": TODAY, "respiration_sleep": 14.0})
    session.commit()
    dto = svc.get_overview(session, TODAY)
    assert dto.missing_history == ["respiration_sleep"]
    assert next(m for m in dto.metrics if m.key == "respiration_sleep").history_from == TODAY
