"""`training plan-today`: the rule-based daily decision (METRICS §10.4), printed and stored."""

import datetime as dt

import typer
from rich.markup import escape
from sqlmodel import Session

from training import planning
from training.cli._app import app, console
from training.coach.workout import total_duration_s
from training.config import get_settings
from training.db.session import get_engine


@app.command("plan-today")
def plan_today(
    force: bool = typer.Option(False, "--force", help="Regenerate even if today already has a plan."),
    sport: str | None = typer.Option(None, "--sport", help="Regenerate for this sport (run | bike)."),
    day: str | None = typer.Option(None, "--date", help="Plan another day (YYYY-MM-DD) instead of today."),
) -> None:
    """Plan today's workout from readiness, load and the weekly template (no network)."""
    target_day = dt.date.fromisoformat(day) if day else dt.date.today()
    with Session(get_engine(get_settings())) as session:
        planning.match_completed(session, target_day)
        try:
            row, decision = planning.plan_day(session, target_day, force=force, sport_override=sport)
        except planning.PlanError as exc:
            console.print(f"[red]{escape(str(exc))}[/]")
            raise typer.Exit(1) from None
        workout = planning.workout_of(row)
        kept = " (existing plan – use --force to regenerate)" if decision is None else ""
        console.print(f"[bold]{target_day}: {escape(row.name)}[/]{kept}")
        if workout.sport != "rest":
            minutes = round(total_duration_s(workout) / 60)
            console.print(f"  {workout.sport}, {minutes} min, estimated load {row.estimated_load:.0f}")
        console.print(f"  {escape(row.reason or '')}")
