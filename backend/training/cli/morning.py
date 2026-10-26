"""`training morning`: the daily automation run (PLAN phase 8) for cron, Task Scheduler or Docker (--loop)."""

import datetime as dt

import typer
from rich.markup import escape
from sqlmodel import Session

from training import log_redaction, morning
from training.cli._app import app, console, err
from training.config import get_settings
from training.db.session import get_engine
from training.keep_awake import keep_awake

DEFAULT_AT = "09:00"  # the daily run (user, 2026-10-26); scripts and docker-compose use the same default
SYMBOLS = {"ok": "[green]✓[/]", "failed": "[red]✗[/]", "skipped": "[dim]–[/]", "waiting": "[yellow]…[/]"}


def _run_once(push: bool, telegram: bool, force_telegram: bool) -> int:
    settings = get_settings()
    try:
        with (
            keep_awake(),  # a PC woken by Task Scheduler must not fall asleep mid-sync
            morning.RunLock(settings.log_dir / morning.LOCK_FILE),
            Session(get_engine(settings)) as session,
        ):
            run = morning.run_morning(
                session,
                settings,
                dt.date.today(),
                push=push,
                telegram=telegram,
                force_telegram=force_telegram,
            )
    except morning.AlreadyRunning as exc:
        err.print(f"[yellow]{escape(str(exc))}[/] – skipped.")
        return morning.EXIT_LOCKED
    for step in run.steps:
        console.print(f"{SYMBOLS.get(step.status, '?')} {step.name:<9} {escape(step.message)}")
    if run.failed:
        console.print("[red]Morning run finished with errors.[/]")
        return morning.EXIT_FAILED
    if run.waiting:
        console.print("[yellow]Waiting for last night's sleep – run again later (until 12:00).[/]")
        return morning.EXIT_WAITING
    console.print("[green]Morning run OK.[/]")
    return 0


@app.command("morning")
def morning_command(
    push: bool = typer.Option(True, "--push/--no-push", help="Push today's workout to Garmin Connect."),
    telegram: bool = typer.Option(True, "--telegram/--no-telegram", help="Send the Telegram message."),
    force_telegram: bool = typer.Option(False, "--force-telegram", help="Send even if already sent today."),
    loop: bool = typer.Option(False, "--loop", help="Stay running and repeat every day at --at (Docker)."),
    at: str = typer.Option(DEFAULT_AT, "--at", help="Local time of the daily run with --loop (HH:MM)."),
    once_per_day: bool = typer.Option(
        False,
        "--once-per-day",
        help="Do nothing if today's run already completed (schedulers repeat the run hourly until 13:00).",
    ),
) -> None:
    """Sync → metrics → plan today → push to Garmin → Telegram. Exit 1 on a failed step, 3 if already running,
    4 while the plan waits for last night's sleep (METRICS §11.2).

    Safe to run twice; logs go to data/logs/training.log (JSON lines) and the run to the diagnostics page.
    """
    settings = get_settings()
    log_file = log_redaction.add_file_handler(settings.log_dir)
    console.print(f"Log: {log_file}")
    if not loop:
        if once_per_day:
            with Session(get_engine(settings)) as session:
                if morning.ran_ok_on(session, dt.date.today()):
                    console.print("Today's morning run already completed – nothing to do.")
                    raise typer.Exit(0)
        if at != DEFAULT_AT:
            err.print("[yellow]--at only applies with --loop; running once now.[/]")
        raise typer.Exit(_run_once(push, telegram, force_telegram))
    try:
        when = morning.parse_time(at)
    except ValueError as exc:
        err.print(f"[red]{escape(str(exc))}[/]")
        raise typer.Exit(2) from None

    def ran_today(day: dt.date) -> bool:
        with Session(get_engine(settings)) as session:
            return morning.ran_ok_on(session, day)  # a failed or waiting run is caught up after a restart

    console.print(f"Daily morning run at {at} (local time).")
    morning.daily_loop(lambda: _run_once(push, telegram, force_telegram), when, ran_today=ran_today)
