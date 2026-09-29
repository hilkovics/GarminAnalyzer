"""services/sleep.py: wellness scenario with a planted sleep → EF correlation, a small DB, an empty one."""

import datetime as dt

import pytest
from sqlalchemy import select
from sqlmodel import Session

from training.db import repo
from training.db.models import DailyLoad
from training.db.session import make_engine, migrate
from training.services import sleep as svc
from training.services import sleep_findings
from training.services.errors import InvalidInputError

from .progress_seeding import progress_db
from .seeding import TODAY
from .wellness_seeding import FIRST_DAY, N_DAYS, wellness_db

N_BOOT = 60  # small: the tests check structure and ordering, not confidence intervals


@pytest.fixture(autouse=True)
def fresh_cache():
    svc.clear_cache()
    yield
    svc.clear_cache()


@pytest.fixture
def engine(tmp_path):
    eng = make_engine(wellness_db(tmp_path))
    yield eng
    eng.dispose()


@pytest.fixture
def session(engine):
    with Session(engine) as s:
        yield s


@pytest.fixture
def small_session(tmp_path):
    eng = make_engine(progress_db(tmp_path))
    with Session(eng) as s:
        yield s
    eng.dispose()


@pytest.fixture
def empty_session(tmp_path):
    path = tmp_path / "empty.db"
    migrate(path)
    eng = make_engine(path)
    with Session(eng) as s:
        yield s
    eng.dispose()


# --- wellness ---------------------------------------------------------------------------------------------


def test_wellness_range_is_sliced_but_baselines_use_the_full_history(session):
    start = FIRST_DAY + dt.timedelta(days=60)
    dto = svc.get_wellness(session, start, TODAY)
    assert (dto.date_from, dto.date_to) == (start, TODAY)
    assert [d.date for d in dto.days] == [
        start + dt.timedelta(days=i) for i in range((TODAY - start).days + 1)
    ]
    first = dto.days[0]
    assert first.baselines.rhr.median == pytest.approx(50, abs=1.5)  # needs the 28 days before the range
    assert first.baselines.rhr.mad is not None and first.baselines.sleep_s.median is not None
    assert first.sleep_debt_7_s is not None
    assert first.readiness is not None and first.readiness_band in ("green", "yellow", "red")
    assert first.steps == 8000 and first.deep_s == pytest.approx(0.2 * first.sleep_s)


def test_wellness_without_bounds_returns_everything_and_early_days_have_no_baseline(session):
    dto = svc.get_wellness(session)
    assert len(dto.days) == N_DAYS
    assert (dto.date_from, dto.date_to) == (FIRST_DAY, TODAY)
    assert dto.days[0].baselines.rhr.median is None  # < 7 valid values before the first day
    assert dto.days[10].baselines.rhr.median is not None


def test_wellness_validates_the_range(session):
    with pytest.raises(InvalidInputError):
        svc.get_wellness(session, TODAY, FIRST_DAY)
    with pytest.raises(InvalidInputError):
        svc.get_wellness(session, dt.date(2000, 1, 1), TODAY)


def test_wellness_empty_db(empty_session):
    dto = svc.get_wellness(empty_session)
    assert dto.days == [] and dto.date_from is None and dto.date_to is None


# --- readiness --------------------------------------------------------------------------------------------


def test_readiness_equals_the_persisted_value_every_day(session):
    persisted = dict(session.execute(select(DailyLoad.date, DailyLoad.readiness)).all())
    checked = 0
    for day, stored in persisted.items():
        dto = svc.get_readiness(session, day)
        assert dto.score == pytest.approx(stored)
        assert dto.available
        checked += 1
    assert checked == N_DAYS
    wellness_days = {d.date: d.readiness for d in svc.get_wellness(session).days}
    assert wellness_days == pytest.approx(persisted)


def test_readiness_components_weights_and_message(session):
    dto = svc.get_readiness(session, TODAY)
    assert [c.name for c in dto.components] == ["rhr", "sleep", "body_battery", "form"]
    assert sum(c.weight for c in dto.components if c.weight is not None) == pytest.approx(1.0)
    by_name = {c.name: c for c in dto.components}
    assert by_name["rhr"].unit == "bpm" and by_name["rhr"].baseline == pytest.approx(50, abs=1.5)
    assert by_name["form"].unit == "TSB" and by_name["form"].baseline is None
    assert (
        dto.message
        == {
            "green": "Trénuj podľa plánu, môžeš pridať.",
            "yellow": "Podľa plánu, nič navyše.",
            "red": "Ľahko alebo voľno.",
        }[dto.band]
    )
    assert (dto.date, dto.available) == (TODAY, True)


def test_sleep_component_falls_back_to_sleep_seconds_without_a_score(session):
    day = FIRST_DAY + dt.timedelta(days=8)  # i % 9 == 8: no sleep score
    sleep = {c.name: c for c in svc.get_readiness(session, day).components}["sleep"]
    assert sleep.unit == "s" and sleep.value is not None and sleep.score is not None
    with_score = {c.name: c for c in svc.get_readiness(session, TODAY - dt.timedelta(days=1)).components}[
        "sleep"
    ]
    assert with_score.unit == "score"


def test_missing_components_renormalize_the_weights(session):
    day = TODAY + dt.timedelta(days=1)  # no daily_load row → no TSB → no form component
    repo.upsert_wellness(session, {"date": day, "rhr": 60.0, "body_battery_wake": 60.0})
    session.commit()
    dto = svc.get_readiness(session, day)
    weights = {c.name: c.weight for c in dto.components}
    assert weights == {
        "rhr": pytest.approx(0.6),
        "sleep": None,
        "body_battery": pytest.approx(0.4),
        "form": None,
    }
    scores = {c.name: c.score for c in dto.components}
    assert scores["sleep"] is None and scores["form"] is None
    assert dto.score == pytest.approx(0.6 * scores["rhr"] + 0.4 * 60.0)


def test_day_without_wellness_is_not_available(session):
    dto = svc.get_readiness(session, dt.date(2020, 1, 1))
    assert not dto.available and dto.score is None and dto.band is None
    assert len(dto.components) == 4 and all(c.score is None and c.weight is None for c in dto.components)
    assert "nie je dosť wellness dát" in dto.message


def test_form_alone_gives_no_score(session):
    day = TODAY + dt.timedelta(days=1)
    session.add(DailyLoad(date=day, load_total=0.0, atl=40.0, ctl=50.0, tsb=5.0))
    session.commit()
    dto = svc.get_readiness(session, day)
    assert not dto.available
    assert {c.name: c.score for c in dto.components}["form"] == pytest.approx(60.0)


# --- correlations -----------------------------------------------------------------------------------------


def test_planted_correlation_is_found_first_with_a_slovak_sentence(session):
    dto = svc.get_correlations(session, "run", n_boot=N_BOOT)
    assert dto.sports == ["run"] and dto.min_n == 30 and dto.n_days["run"] > 80
    assert dto.caveat == sleep_findings.CAVEAT
    assert all(w in dto.caveat for w in ("kauzalita", "teplo", "kofeín", "choroba", "násobné"))
    assert dto.findings and all(f.status == "ok" and f.n >= 30 for f in dto.findings)
    magnitudes = [abs(f.headline_rho) for f in dto.findings if f.headline_rho is not None]
    assert magnitudes == sorted(magnitudes, reverse=True)
    top = dto.findings[0]
    assert top.outcome == "ef" and top.predictor_base in ("sleep_s", "deep_s", "rem_s")
    assert top.headline_rho is not None and top.headline_rho > 0.7 and not top.uncertain
    assert top.sentence.startswith("Keď ") and "tvoj EF pri behu je vyšší – silná súvislosť" in top.sentence
    sleep_s = next(f for f in dto.findings if (f.predictor, f.outcome) == ("sleep_s_lag0", "ef"))
    assert (
        sleep_s.sentence
        == "Keď spíš dlhšie (noc pred tréningom), tvoj EF pri behu je vyšší – silná súvislosť."
    )
    assert (sleep_s.predictor_base, sleep_s.variant) == ("sleep_s", "lag0")
    assert sleep_s.partial_rho is not None and sleep_s.ci_low is not None


def test_bike_has_too_few_days_and_is_listed_as_insufficient(session):
    dto = svc.get_correlations(session, n_boot=N_BOOT)
    assert dto.sports == ["run", "bike"] and set(dto.n_days) == {"run", "bike"} and dto.n_days["bike"] == 10
    assert not [f for f in dto.findings if f.sport == "bike"]
    bike = [i for i in dto.insufficient if i.sport == "bike"]
    assert bike and all(i.n < 30 and i.rho is None and i.status == "insufficient_data" for i in bike)
    assert "nedostatok dát (n = 10, treba aspoň 30)" in bike[0].sentence
    only_bike = svc.get_correlations(session, "bike", n_boot=N_BOOT)
    assert only_bike.findings == [] and len(only_bike.insufficient) == len(bike)


def test_small_db_has_no_findings(small_session):
    dto = svc.get_correlations(small_session, n_boot=N_BOOT)
    assert dto.findings == [] and dto.insufficient
    assert all(i.n < 30 for i in dto.insufficient)
    assert dto.caveat


def test_empty_db_has_no_findings(empty_session):
    dto = svc.get_correlations(empty_session, n_boot=N_BOOT)
    assert dto.findings == [] and dto.n_days == {"run": 0, "bike": 0}
    assert len(dto.insufficient) > 0


def test_invalid_sport_and_n_boot(session):
    with pytest.raises(InvalidInputError):
        svc.get_correlations(session, "swim")
    with pytest.raises(InvalidInputError):
        svc.get_correlations(session, "run", n_boot=0)


def test_cache_reuses_results_until_the_data_changes(session, monkeypatch):
    calls = []
    real = svc.correlations
    monkeypatch.setattr(svc, "correlations", lambda *a, **k: calls.append(a[1]) or real(*a, **k))
    first = svc.get_correlations(session, "run", n_boot=N_BOOT)
    again = svc.get_correlations(session, "run", n_boot=N_BOOT)
    assert calls == ["run"] and again == first
    svc.get_correlations(session, n_boot=N_BOOT)  # run is cached, only bike is new
    assert calls == ["run", "bike"]
    svc.get_correlations(session, "run", n_boot=N_BOOT + 1)  # another n_boot is another entry
    assert calls == ["run", "bike", "run"]
    repo.upsert_wellness(session, {"date": TODAY + dt.timedelta(days=1), "sleep_s": 7 * 3600.0})
    session.commit()
    svc.get_correlations(session, "run", n_boot=N_BOOT)
    assert calls == ["run", "bike", "run", "run"]


def test_cache_is_bounded(session, monkeypatch):
    monkeypatch.setattr(svc, "CACHE_SIZE", 3)
    monkeypatch.setattr(svc, "_sport_findings", lambda s, sport, n_boot: ([], 0))
    for n in range(1, 8):
        svc.get_correlations(session, "run", n_boot=n)
    assert len(svc._cache) == 3


# --- sentences --------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("rho", "word"),
    [(0.1, "slabá"), (0.29, "slabá"), (0.3, "stredná"), (-0.49, "stredná"), (0.5, "silná"), (-0.9, "silná")],
)
def test_strength_words(rho, word):
    assert sleep_findings.strength_word(rho) == word


def _result(**kw):
    from training.analysis.correlation import CorrelationResult

    base = dict(
        sport="run", predictor="rhr_lag1", outcome="decoupling_pct", n=40, status="ok", rho=-0.35, p=0.03,
        ci_low=-0.6, ci_high=-0.1, partial_n=40, partial_rho=None, partial_p=None, partial_ci_low=None,
        partial_ci_high=None, q_contrast=None, q_ci_low=None, q_ci_high=None, q_n_bottom=None, q_n_top=None,
        uncertain=False,
    )  # fmt: skip
    return CorrelationResult(**{**base, **kw})


def test_sentence_direction_uncertainty_and_variants():
    text = sleep_findings.sentence(_result())
    assert text == (
        "Keď máš vyšší pokojový tep (dve noci pred tréningom), "
        "tvoj aeróbny decoupling pri behu je nižší (lepší)"
        " – stredná súvislosť."
    )
    uncertain = sleep_findings.sentence(_result(partial_rho=0.1, uncertain=True, sport="bike", outcome="ef"))
    assert uncertain == (
        "Keď máš vyšší pokojový tep (dve noci pred tréningom), tvoj EF na bicykli je vyšší – slabá súvislosť"
        " (neisté – interval obsahuje 0)."
    )
    debt = sleep_findings.sentence(_result(predictor="sleep_debt_7", outcome="pace_at_ref_hr_day", rho=0.6))
    assert debt == (
        "Keď máš väčší spánkový dlh za posledných 7 nocí, "
        "tvoje tempo pri referenčnom tepe pri behu je rýchlejšie"
        " – silná súvislosť."
    )
    assert sleep_findings.split_predictor("sleep_s_mean3") == ("sleep_s", "mean3")
    assert "konštantná" in sleep_findings.sentence(_result(rho=None, status="ok"))
