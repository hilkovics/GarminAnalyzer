"""`training weekly-report`: the optional weekly AI report (phase 7, needs TRAINING_ANTHROPIC_API_KEY)."""

import datetime as dt

import typer
from rich.markup import escape
from sqlmodel import Session

from training.cli._app import app, console
from training.coach import llm
from training.config import get_settings
from training.db.session import get_engine
from training.services import report
from training.services.errors import ServiceError


@app.command("weekly-report")
def weekly_report(
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the prompt; no API call, nothing stored."),
) -> None:
    """Write this week's Slovak report (docs/reports/YYYY-Www.md) from the last 7 days, PMC and the plan."""
    settings = get_settings()
    today = dt.date.today()
    with Session(get_engine(settings)) as session:
        try:
            if dry_run:
                system, user = llm.build_weekly_prompt(report.weekly_inputs(session, today))
                console.print(escape(f"[system]\n{system}\n[user]\n{user}"))
                return
            created = report.create_weekly_report(session, today, settings)
        except ServiceError as exc:
            console.print(f"[red]{escape(str(exc))}[/]")
            raise typer.Exit(1) from None
    console.print(f"Report {created.week} stored in {settings.reports_dir}.")
