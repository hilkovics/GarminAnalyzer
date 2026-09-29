"""services/plan.py: goal, season, week, today's decision, status – on the seeded scenario and an empty DB."""

import datetime as dt

import pytest
from sqlmodel import Session

from training import planning
from training.coach.workout import HrZoneTarget, RepeatStep, Step, Workout, to_structure
from training.db.models import PlannedWorkout
from training.db.session import make_engine, migrate
from training.services import plan as svc, settings as settings_svc
from training.services.dto import AthleteIn, GoalIn, PreferredDayDTO
from training.services.errors import InvalidInputError, NotFoundError

from .seeding import TODAY, seeded_db

MONDAY = dt.date(2026, 9, 14)  # the seeded run day of TODAY's week (TODAY is Wednesday)
DAY = dt.timedelta(days=1)


@pytest.fixture
def session(tmp_path):
    engine = make_engine(seeded_db(tmp_path))
    with Session(engine) as s:
        yield s
    engine.dispose()


@pytest.fixture
def empty_session(tmp_path):
    path = tmp_path / "empty.db"
    migrate(path)
    engine = make_engine(path)
    with Session(engine) as s:
        yield s
    engine.dispose()


def _hr(zone: int) -> HrZoneTarget:
    return HrZoneTarget(zone=zone)


def add_plan(session, day, *, sport="run", status="planned") -> int:
    workout = Workout(
        sport=sport,
        name="Prahové 5x6",
        key="threshold",
        slot="q1",
        steps=[
            Step(type="warmup", duration_s=900, target=_hr(2)),
            RepeatStep(
                count=5,
                steps=[
                    Step(type="work", duration_s=360, target=_hr(4)),
                    Step(type="recovery", duration_s=120, target=_hr(1)),
                ],
            ),
            Step(type="cooldown", duration_s=600, target=_hr(1)),
        ],
    )
    row = PlannedWorkout(
        date=day, sport=sport, name=workout.name, structure=to_structure(workout), status=status
    )
    session.add(row)
    session.commit()
    return row.id


# --- today ------------------------------------------------------------------------------------------------


def test_today_is_decided_once_then_returned_unchanged(session):
    first = svc.get_today(session, TODAY)
    again = svc.get_today(session, TODAY)
    assert first.created and not again.created
    assert first.workout.id == again.workout.id and first.workout.reason == again.reason
    assert first.rule is not None and again.rule is None
    assert first.date == TODAY and first.workout.status == "planned" and not first.workout.missed
    assert first.readiness is None and first.readiness_band is None  # the seeded DB has no wellness
    assert first.tsb is not None and first.acwr is not None


def test_workout_steps_are_flattened_with_repeat_groups(session):
    dto = svc.get_planned(session, add_plan(session, TODAY), today=TODAY)
    assert dto.duration_s == 900 + 5 * 480 + 600 and dto.key == "threshold" and dto.slot == "q1"
    assert [(s.type, s.zone, s.repeat, s.group) for s in dto.steps] == [
        ("warmup", 2, None, None),
        ("work", 4, 5, 0),
        ("recovery", 1, 5, 0),
        ("cooldown", 1, None, None),
    ]
    assert dto.structure["steps"][1]["count"] == 5


def test_regenerate_with_another_sport_replaces_the_plan(session):
    first = svc.get_today(session, TODAY)
    other = svc.regenerate(session, TODAY, "bike")
    assert other.created and other.workout.sport in ("bike", "rest")
    assert other.workout.id != first.workout.id or other.workout.sport == first.workout.sport
    assert len(planning.planned_for(session, TODAY)) == 1


def test_regenerate_errors(session):
    with pytest.raises(InvalidInputError):
        svc.regenerate(session, TODAY, "swim")
    dto = svc.get_today(session, TODAY)
    svc.set_status(session, dto.workout.id, "done", today=TODAY)
    with pytest.raises(InvalidInputError, match="done or skipped"):
        svc.regenerate(session, TODAY)


def test_status_changes_and_errors(session):
    plan_id = svc.get_today(session, TODAY).workout.id
    assert svc.set_status(session, plan_id, "skipped", today=TODAY).status == "skipped"
    assert svc.set_status(session, plan_id, "planned", today=TODAY).status == "planned"
    with pytest.raises(NotFoundError):
        svc.set_status(session, 9999, "done", today=TODAY)
    with pytest.raises(NotFoundError):
        svc.get_planned(session, 9999, today=TODAY)
    with pytest.raises(InvalidInputError):
        svc.set_status(session, plan_id, "pushed", today=TODAY)


def test_done_links_the_matching_activity_and_its_load(session):
    plan_id = add_plan(session, MONDAY)  # the seeded Monday run
    dto = svc.set_status(session, plan_id, "done", today=TODAY)
    assert dto.status == "done" and dto.completed_activity_id is not None
    assert dto.actual_load == pytest.approx(33.3, abs=1.0) and not dto.missed


def test_missed_flag(session):
    yesterday = add_plan(session, TODAY - DAY)
    today_id = add_plan(session, TODAY)
    skipped = add_plan(session, TODAY - 2 * DAY, status="skipped")
    assert svc.get_planned(session, yesterday, today=TODAY).missed
    assert not svc.get_planned(session, today_id, today=TODAY).missed
    assert not svc.get_planned(session, skipped, today=TODAY).missed
    assert not svc.get_planned(session, yesterday, today=TODAY - 2 * DAY).missed


# --- week -------------------------------------------------------------------------------------------------


def test_week_days_show_planned_versus_actual(session):
    add_plan(session, MONDAY)
    planning.match_completed(session, TODAY)
    week = svc.get_week(session, TODAY, today=TODAY)
    assert week.monday == MONDAY and len(week.days) == 7
    assert [d.weekday for d in week.days] == ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
    monday, tuesday, wednesday = week.days[:3]
    assert monday.planned and monday.planned.status == "done" and monday.planned.actual_load
    assert monday.activities == 1 and monday.actual_load == pytest.approx(33.3, abs=1.0)
    assert tuesday.planned is None and tuesday.activities == 0 and tuesday.actual_load == 0
    assert wednesday.activities == 1  # the seeded ride
    assert week.done_load == pytest.approx(monday.actual_load + wednesday.actual_load)
    assert week.remaining_load == pytest.approx(max(0.0, week.target_load - week.done_load))
    assert week.run_target + week.bike_target == pytest.approx(week.target_load)
    assert [d.role for d in week.days] == ["rest", "q1", "easy", "easy", "easy", "long", "easy"]  # Base


def test_week_of_another_date_uses_its_own_monday(session):
    week = svc.get_week(session, MONDAY - 7 * DAY + 3 * DAY, today=TODAY)
    assert week.monday == MONDAY - 7 * DAY and week.done_load > 0


# --- goal and season --------------------------------------------------------------------------------------


def test_goal_crud_and_single_active_goal(session):
    assert svc.get_goal(session, TODAY) is None
    first = svc.set_goal(
        session, GoalIn(race_date=TODAY + 60 * DAY, distance_m=10000, sport="run"), today=TODAY
    )
    second = svc.set_goal(
        session,
        GoalIn(race_date=TODAY + 90 * DAY, distance_m=40000, target_time_s=5400, sport="bike"),
        today=TODAY,
    )
    got = svc.get_goal(session, TODAY)
    assert got == second and got.id != first.id and got.sport == "bike" and got.target_time_s == 5400
    svc.clear_goal(session)
    assert svc.get_goal(session, TODAY) is None
    svc.clear_goal(session)  # idempotent


@pytest.mark.parametrize(
    "goal",
    [GoalIn(race_date=TODAY - DAY, sport="run"), GoalIn(race_date=TODAY + DAY, sport="swim")],
)
def test_goal_validation(session, goal):
    with pytest.raises(InvalidInputError):
        svc.set_goal(session, goal, today=TODAY)
    assert svc.get_goal(session, TODAY) is None


def test_race_today_is_allowed_and_inactive_goal_keeps_the_active_one(session):
    svc.set_goal(session, GoalIn(race_date=TODAY, sport="run"), today=TODAY)
    kept = svc.get_goal(session, TODAY)
    svc.set_goal(session, GoalIn(race_date=TODAY + 30 * DAY, active=False), today=TODAY)
    assert svc.get_goal(session, TODAY) == kept


def test_season_without_goal_is_a_perpetual_base_cycle(session):
    season = svc.get_season(session, TODAY)
    assert season.goal is None and season.current_phase == "base" and len(season.weeks) == 20
    assert season.weeks[0].monday == MONDAY and season.weeks[0].is_current
    assert not any(w.is_race_week for w in season.weeks)
    assert {w.phase for w in season.weeks} == {"base"} and any(w.recovery for w in season.weeks)


def test_season_with_a_goal_walks_through_the_phases(session):
    race = MONDAY + 15 * 7 * DAY + 5 * DAY  # a Saturday, 15 weeks ahead
    svc.set_goal(session, GoalIn(race_date=race, distance_m=21097.5, sport="run"), today=TODAY)
    season = svc.get_season(session, TODAY)
    assert season.goal is not None and season.goal.race_date == race
    assert len(season.weeks) == 17  # this week … race week + 1
    phases = [w.phase for w in season.weeks]
    assert phases[0] == "base" and season.current_phase == "base"
    assert phases[:16:1] == sorted(phases[:16], key=("base", "build", "peak", "taper").index)
    assert {"base", "build", "peak", "taper"} <= set(phases)
    race_week = [w for w in season.weeks if w.is_race_week]
    assert len(race_week) == 1 and race_week[0].phase == "taper" and race_week[0].days_to_race == 5
    assert season.weeks[-1].monday == race_week[0].monday + 7 * DAY
    assert season.weeks[-1].days_to_race is None  # after the race: no-goal cycle
    taper = [w.target_load for w in season.weeks if w.phase == "taper"]
    assert taper and max(taper) < max(w.target_load for w in season.weeks if w.phase == "peak")
    assert all(w.run_target + w.bike_target == pytest.approx(w.target_load) for w in season.weeks)


# --- empty database ---------------------------------------------------------------------------------------


def test_everything_works_on_an_empty_db(empty_session):
    today = svc.get_today(empty_session, TODAY)
    assert today.created and today.readiness is None and today.tsb is None and today.acwr is None
    week = svc.get_week(empty_session, TODAY, today=TODAY)
    assert week.done_load == 0 and all(d.activities == 0 for d in week.days)
    assert sum(d.planned is not None for d in week.days) == 1
    season = svc.get_season(empty_session, TODAY)
    assert len(season.weeks) == 20 and season.weeks[0].target_load == pytest.approx(
        7 * 6 * 4
    )  # CTL 0, Base ramp 4
    assert svc.get_goal(empty_session, TODAY) is None


# --- preferred days (settings service) --------------------------------------------------------------------


def test_preferred_days_are_validated_stored_and_reset(session):
    days = {"mon": PreferredDayDTO(role="long", sport="bike"), "sat": PreferredDayDTO(role="rest")}
    athlete = settings_svc.update_athlete(session, AthleteIn(preferred_days=days), today=TODAY)
    assert athlete.preferred_days["mon"] == PreferredDayDTO(role="long", sport="bike")
    assert athlete.preferred_days["tue"] == PreferredDayDTO(role="q1", sport=None)  # default filled in
    assert len(athlete.preferred_days) == 7
    assert svc.get_week(session, TODAY, today=TODAY).days[0].role == "long"
    with pytest.raises(InvalidInputError):
        settings_svc.update_athlete(
            session, AthleteIn(preferred_days={"mon": PreferredDayDTO(role="sprint")}), today=TODAY
        )
    with pytest.raises(InvalidInputError):
        settings_svc.update_athlete(
            session, AthleteIn(preferred_days={"xyz": PreferredDayDTO(role="easy")}), today=TODAY
        )
    reset = settings_svc.update_athlete(session, AthleteIn(preferred_days={}), today=TODAY)
    assert reset.preferred_days["mon"].role == "rest" and reset.max_hr == 190.0
