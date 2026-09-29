"""AppTest runs of the Plán page on real (seeded and empty) databases, through the real services."""

import datetime as dt
from contextlib import contextmanager

import pytest
from sqlalchemy import select
from sqlmodel import Session

from tests.test_ui_support import TODAY, figures, run_page, setup_ui, texts, trace_names, ui_module
from training.db.models import Athlete, Goal, PlannedWorkout
from training.db.session import make_engine, migrate
from training.services import plan as svc, settings as settings_svc
from training.services.dto import (
    DailyDecisionDTO,
    GoalDTO,
    PlannedWorkoutDTO,
    SeasonDTO,
    SeasonWeekDTO,
    WeekDayDTO,
    WeekPlanDTO,
    WorkoutStepDTO,
)

from .seeding import TODAY as SEED_TODAY, seeded_db

DAY = dt.timedelta(days=1)


@pytest.fixture(autouse=True)
def ui(monkeypatch):
    setup_ui(monkeypatch)


def use_db(monkeypatch, path):
    engine = make_engine(path)

    @contextmanager
    def session():
        with Session(engine) as s:
            yield s
            s.commit()

    monkeypatch.setattr(ui_module("_db"), "session", session)
    monkeypatch.setattr(ui_module("_db"), "today", lambda: SEED_TODAY)
    return engine


@pytest.fixture
def seeded(monkeypatch, tmp_path):
    engine = use_db(monkeypatch, seeded_db(tmp_path))
    yield engine
    engine.dispose()


@pytest.fixture
def empty(monkeypatch, tmp_path):
    path = tmp_path / "empty.db"
    migrate(path)
    engine = use_db(monkeypatch, path)
    yield engine
    engine.dispose()


def rows(engine, model):
    with Session(engine) as s:
        return list(s.execute(select(model)).scalars())


def button(at, label):
    matches = [b for b in at.button if b.label == label]
    assert matches, f"no button {label!r}; have {[b.label for b in at.button]}"
    return matches[0]


def plan_rows(engine):
    return rows(engine, PlannedWorkout)


# --- rendering --------------------------------------------------------------------------------------------


def test_page_renders_on_a_seeded_db(seeded):
    at = run_page("plan")
    assert not at.exception and not at.error
    assert at.title[0].value == "Plán"
    assert [s.value for s in at.subheader] == ["Dnešný tréning", "Tento týždeň", "Sezóna"]
    season, week = figures(at)[1], figures(at)[0]
    assert trace_names(week) == ["Plán (odhad)", "Skutočnosť"] and len(week["data"][0]["x"]) == 7
    assert "Základ" in trace_names(season)[0] and "Tento týždeň" in trace_names(season)
    assert "Cieľ nie je nastavený" in texts(at)
    assert len(plan_rows(seeded)) == 1  # today was decided by viewing the page
    table = next(d.value for d in at.dataframe)
    assert list(table["Deň"].str[:2]) == ["Po", "Ut", "St", "Št", "Pi", "So", "Ne"]
    assert table["Stav"].iloc[0] == "voľno" and table["Stav"].iloc[2] == "plánované"


def test_page_renders_on_an_empty_db(empty):
    at = run_page("plan")
    assert not at.exception and not at.error
    assert len(plan_rows(empty)) == 1
    assert "Pripravenosť: bez wellness dát." in texts(at)


def test_page_with_a_goal_shows_the_race_marker_and_all_phases(seeded):
    with Session(seeded) as s:
        svc.set_goal(
            s,
            svc.GoalIn(race_date=SEED_TODAY + 100 * DAY, distance_m=10000, target_time_s=2400),
            today=SEED_TODAY,
        )
    at = run_page("plan")
    assert not at.exception
    season = figures(at)[1]
    names = trace_names(season)
    assert "Preteky" in names and any(n and n.startswith("Ladenie") for n in names)
    assert any(n and n.startswith("Budovanie") for n in names)
    assert "0:40:00" in texts(at) and "10.0 km" in texts(at)


# --- buttons ----------------------------------------------------------------------------------------------


def test_done_skipped_and_undo_buttons_call_the_service(seeded):
    at = run_page("plan")
    button(at, "Hotovo").click().run()
    assert not at.exception and plan_rows(seeded)[0].status == "done"
    assert any("Hotovo." in s.value for s in at.success)
    assert [b.label for b in at.button if b.key in ("plan_done", "plan_skip")] == []
    button(at, "Späť na plánované").click().run()
    assert plan_rows(seeded)[0].status == "planned"
    button(at, "Vynechať").click().run()
    assert plan_rows(seeded)[0].status == "skipped"


def test_regenerate_with_another_sport(seeded):
    at = run_page("plan")
    before = plan_rows(seeded)[0]
    at.selectbox(key="plan_regen_sport").set_value("bike").run()
    button(at, "Prepočítať").click().run()
    assert not at.exception and not at.error
    after = plan_rows(seeded)
    assert len(after) == 1 and after[0].sport in ("bike", "rest")
    assert after[0].id != before.id


def test_regenerate_is_disabled_once_the_workout_is_done(seeded):
    at = run_page("plan")
    button(at, "Hotovo").click().run()
    assert button(at, "Prepočítať").disabled


def test_service_errors_are_shown_not_raised(seeded, monkeypatch):
    from training.services.errors import InvalidInputError

    at = run_page("plan")

    def boom(*args, **kwargs):
        raise InvalidInputError("Nejde to.")

    monkeypatch.setattr(svc, "regenerate", boom)
    button(at, "Prepočítať").click().run()
    assert not at.exception and at.error[0].value == "Nejde to."


def test_goal_form_saves_and_clear_button_removes(seeded):
    at = run_page("plan")
    at.date_input(key="goal_date").set_value(SEED_TODAY + 60 * DAY)
    at.selectbox(key="goal_preset").set_value("Polmaratón")
    at.text_input(key="goal_time").set_value("1:45:00")
    at.selectbox(key="goal_sport").set_value("run")
    button(at, "Uložiť cieľ").click().run()
    assert not at.exception and not at.error
    goals = rows(seeded, Goal)
    assert len(goals) == 1 and goals[0].distance_m == 21097.5 and goals[0].target_time_s == 6300
    assert goals[0].race_date == SEED_TODAY + 60 * DAY
    button(at, "Zmazať cieľ").click().run()
    assert not at.exception and not any(g.active for g in rows(seeded, Goal))


def test_goal_form_custom_distance_and_bad_time(seeded):
    at = run_page("plan")
    at.selectbox(key="goal_preset").set_value("Vlastná")
    at.number_input(key="goal_km").set_value(15.0)
    at.text_input(key="goal_time").set_value("rýchlo")
    button(at, "Uložiť cieľ").click().run()
    assert not at.exception and "h:mm:ss" in at.error[0].value and not rows(seeded, Goal)
    at.text_input(key="goal_time").set_value("")
    button(at, "Uložiť cieľ").click().run()
    assert rows(seeded, Goal)[0].distance_m == 15000.0 and rows(seeded, Goal)[0].target_time_s is None


def test_preferred_days_editor_saves_and_resets(seeded):
    at = run_page("plan")
    at.selectbox(key="pd_role_mon").set_value("long")
    at.selectbox(key="pd_sport_mon").set_value("bike")
    at.selectbox(key="pd_role_sat").set_value("rest")
    button(at, "Uložiť dni").click().run()
    assert not at.exception and not at.error
    athlete = rows(seeded, Athlete)[0]
    assert athlete.preferred_days["mon"] == {"role": "long", "sport": "bike"}
    assert athlete.preferred_days["sat"] == "rest" and athlete.max_hr == 190.0
    with Session(seeded) as s:
        dto = settings_svc.get_settings(s, today=SEED_TODAY).athlete
    assert dto.preferred_days["mon"].sport == "bike"
    at = run_page("plan")
    assert at.selectbox(key="pd_role_mon").value == "long"
    button(at, "Predvolené dni").click().run()
    assert rows(seeded, Athlete)[0].preferred_days is None


# --- samples for the faked-service navigation test --------------------------------------------------------


def step(kind, seconds, zone, *, repeat=None, group=None) -> WorkoutStepDTO:
    return WorkoutStepDTO(
        type=kind, duration_s=seconds, target_kind="hr_zone", zone=zone, repeat=repeat, group=group
    )


def sample_planned(**overrides) -> PlannedWorkoutDTO:
    values = {
        "id": 1,
        "date": TODAY,
        "sport": "run",
        "name": "Prahové 5×6",
        "key": "threshold",
        "slot": "q1",
        "status": "planned",
        "missed": False,
        "estimated_load": 85.0,
        "duration_s": 4500,
        "reason": "Podľa plánu.",
        "completed_activity_id": None,
        "actual_load": None,
        "steps": [
            WorkoutStepDTO(
                type="warmup", duration_s=900, target_kind="hr_zone", zone=2, repeat=None, group=None
            ),
            WorkoutStepDTO(type="work", duration_s=360, target_kind="hr_zone", zone=4, repeat=5, group=0),
            WorkoutStepDTO(type="recovery", duration_s=120, target_kind="hr_zone", zone=1, repeat=5, group=0),
        ],
        "structure": {},
    }
    return PlannedWorkoutDTO(**{**values, **overrides})


def sample_decision(**overrides) -> DailyDecisionDTO:
    values = {
        "date": TODAY,
        "workout": sample_planned(),
        "reason": "Podľa plánu.",
        "rule": 3,
        "readiness": 77.4,
        "readiness_band": "green",
        "acwr": 1.1,
        "tsb": -3.0,
        "created": False,
    }
    return DailyDecisionDTO(**{**values, **overrides})


def sample_week() -> WeekPlanDTO:
    monday = dt.date(2026, 9, 28)
    days = [
        WeekDayDTO(
            date=monday + i * DAY,
            weekday=w,
            role="rest" if i == 0 else "easy",
            planned=None,
            actual_load=0.0,
            activities=0,
        )
        for i, w in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))
    ]
    return WeekPlanDTO(
        monday=monday,
        phase="build",
        recovery=False,
        target_load=400.0,
        run_target=250.0,
        bike_target=150.0,
        done_load=0.0,
        remaining_load=400.0,
        days=days,
    )


def sample_season() -> SeasonDTO:
    weeks = [
        SeasonWeekDTO(
            monday=dt.date(2026, 9, 28) + 7 * i * DAY,
            phase="build",
            recovery=i == 3,
            days_to_race=60 - 7 * i,
            ctl_start=50.0,
            target_load=400.0,
            run_target=250.0,
            bike_target=150.0,
            is_current=i == 0,
            is_race_week=i == 5,
        )
        for i in range(6)
    ]
    goal = GoalDTO(
        id=1,
        race_date=dt.date(2026, 11, 7),
        distance_m=10000.0,
        target_time_s=2400.0,
        sport="run",
        active=True,
    )
    return SeasonDTO(today=TODAY, goal=goal, current_phase="build", weeks=weeks)


def patch_plan(monkeypatch, decision=None):
    from tests.test_ui_support import patch_service

    season = sample_season()
    patch_service(
        monkeypatch,
        "plan",
        get_today=lambda session, today: decision or sample_decision(),
        get_week=lambda session, day, *, today: sample_week(),
        get_season=lambda session, today: season,
        get_goal=lambda session, today: season.goal,
    )


def test_today_card_text_with_faked_services(monkeypatch):
    from tests.test_ui_samples import sample_settings
    from tests.test_ui_support import patch_service

    patch_plan(monkeypatch)
    patch_service(monkeypatch, "settings", get_settings=lambda session, *, today: sample_settings())
    at = run_page("plan")
    assert not at.exception
    text = texts(at)
    assert "Prahové 5×6" in text and ":blue-badge[plánované]" in text
    assert "Rozcvička 15 min Z2" in text and "5× (6 min Z4 / 2 min Z1)" in text
    assert "Podľa plánu." in text and "Pripravenosť: 77" in text and ":green-badge[zelená]" in text
    assert "07. 11. 2026" in text and "0:40:00" in text
    assert not any(b.label == "Späť na plánované" for b in at.button)
    hatched = [
        t for t in figures(at)[1]["data"] if t.get("marker", {}).get("pattern", {}).get("shape") == "/"
    ]
    assert len(hatched) == 1 and hatched[0]["x"] == ["2026-10-19"]


def test_missed_and_rest_cards(monkeypatch):
    from tests.test_ui_samples import sample_settings
    from tests.test_ui_support import patch_service

    patch_service(monkeypatch, "settings", get_settings=lambda session, *, today: sample_settings())
    patch_plan(monkeypatch, sample_decision(workout=sample_planned(missed=True)))
    assert ":red-badge[zmeškané]" in texts(run_page("plan"))
    rest = sample_planned(sport="rest", name="Voľno", steps=[], estimated_load=0.0, duration_s=0, slot=None)
    patch_plan(monkeypatch, sample_decision(workout=rest, readiness=None, readiness_band=None))
    at = run_page("plan")
    assert not at.exception and "Dnes voľno" in texts(at)
    assert not any(b.label in ("Hotovo", "Vynechať") for b in at.button)


def test_push_button_calls_the_push_service(seeded, monkeypatch):
    from training.services import plan_push

    calls = []
    monkeypatch.setattr(plan_push, "push_planned", lambda s, pid, settings: calls.append(pid))
    at = run_page("plan")
    button(at, "Poslať do Garmin").click().run()
    assert not at.exception and not at.error and len(calls) == 1
