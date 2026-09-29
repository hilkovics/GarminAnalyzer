"""`training telegram-morning`: the optional Telegram morning message (phase 7)."""

import datetime as dt

import typer
from rich.markup import escape
from sqlmodel import Session

from training.cli._app import app, console
from training.config import get_settings
from training.db.session import get_engine
from training.services import notify


@app.command("telegram-morning")
def telegram_morning(
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the message instead of sending it."),
) -> None:
    """Send readiness, today's workout and yesterday's load to Telegram (never fails the morning chain)."""
    settings = get_settings()
    today = dt.date.today()
    with Session(get_engine(settings)) as session:
        if dry_run:
            console.print(escape(notify.morning_message(session, today).text))
            return
        if not notify.is_configured(settings):
            console.print("Telegram is not configured (TRAINING_TELEGRAM_TOKEN / TRAINING_TELEGRAM_CHAT_ID).")
            return
        if notify.send_morning(session, today, settings):
            console.print("Telegram message sent.")
        else:
            console.print("[yellow]Telegram message not sent (see log); continuing.[/]")
