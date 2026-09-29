"""`training sync` / `training backfill` / `training db-stats` (+ metric update after ingest)."""

import datetime as dt
import logging
from collections.abc import Iterator
from contextlib import contextmanager

import requests
import typer
from rich.markup import escape
from rich.table import Table
from sqlmodel import Session

from training import pipeline, planning
from training.cli._app import app, console, err
from training.config import get_settings
from training.db import repo
from training.db.session import get_engine
from training.garmin import client as garmin_client
from training.garmin.backfill import backfill as run_backfill
from training.garmin.sync import (
    FAILED_ACTIVITIES,
    FAILED_WELLNESS,
    PENDING_ACTIVITIES,
    PENDING_WELLNESS,
    Ingestor,
    SyncResult,
    raw_sink_for,
    sync as run_sync,
)

log = logging.getLogger(__name__)


@contextmanager
def _garmin_session() -> Iterator[tuple[Session, garmin_client.GarminClient]]:
    """DB session (migrated to head) + logged-in Garmin client whose responses go straight to raw_garmin."""
    settings = get_settings()
    engine = get_engine(settings)
    with Session(engine) as session:
        try:
            client = garmin_client.GarminClient.from_settings(settings, raw_sink=raw_sink_for(session))
        except garmin_client.GarminConnectAuthenticationError as exc:
            err.print(f"[red]Not logged in:[/] {escape(str(exc))}")
            raise typer.Exit(1) from None
        except (
            garmin_client.GarminConnectConnectionError,
            requests.ConnectionError,
            requests.Timeout,
        ) as exc:
            err.print(f"[red]Could not reach Garmin Connect:[/] {type(exc).__name__}")
            raise typer.Exit(1) from None
        try:
            yield session, client
        except garmin_client.GarminConnectTooManyRequestsError:
            err.print(
                "[red]Garmin is rate-limiting (429).[/] Progress is saved – run the same command again later."
            )
            raise typer.Exit(1) from None
        except garmin_client.GarminConnectAuthenticationError as exc:
            err.print(f"[red]Garmin rejected the tokens:[/] {escape(str(exc))} – run `training login`.")
            raise typer.Exit(1) from None
        except (
            garmin_client.GarminConnectConnectionError,
            requests.ConnectionError,
            requests.Timeout,
        ) as exc:
            err.print(
                f"[red]Garmin Connect is unreachable or failing:[/] {type(exc).__name__}. "
                "Progress is saved – run the same command again later."
            )
            raise typer.Exit(1) from None
        except KeyboardInterrupt:
            err.print("[yellow]Interrupted.[/] Progress is saved – run the same command again to continue.")
            raise typer.Exit(130) from None


def _report(result: SyncResult) -> None:
    console.print(
        f"Activities: [green]{result.activities_new} new[/], {result.activities_updated} updated, "
        f"{result.activities_unchanged} unchanged · wellness days: {result.wellness_days}"
    )
    if result.activities_pending:
        console.print(
            f"[yellow]{result.activities_pending} activities incomplete[/] – retried on the next run."
        )
    if result.errors:
        console.print(f"[yellow]{len(result.errors)} endpoint calls failed[/] (details in the log):")
        for line in result.errors[:10]:
            console.print(f"  - {escape(line)}")
        if len(result.errors) > 10:
            console.print(f"  … and {len(result.errors) - 10} more")


def _after_ingest(session: Session, result: SyncResult) -> None:
    """Recompute metrics for what the sync/backfill changed (PLAN phase 2 step 5)."""
    done = pipeline.update_after_sync(session, result.affected, today=dt.date.today())
    console.print(f"Metrics: {done.metrics_computed} activities, PMC {done.daily_load_days} days")
    for line in done.errors[:5]:
        console.print(f"  [yellow]- {escape(line)}[/]")


@app.command()
def sync(
    retry_failed: bool = typer.Option(
        False, "--retry-failed", help="Also retry activities/days that failed repeatedly before."
    ),
) -> None:
    """Incremental sync of activities and wellness (idempotent; safe to run from cron)."""
    with _garmin_session() as (session, client):
        if retry_failed:
            console.print(f"Retrying {Ingestor(session, client).retry_failed()} previously failed items.")
        result = run_sync(session, client, dt.date.today())
        _report(result)
        _after_ingest(session, result)
        _plan_today(session)


def _plan_today(session: Session) -> None:
    """Nightly coach step (PLAN phase 6): match done workouts, plan today if nothing is planned yet."""
    try:
        row = planning.nightly(session, dt.date.today())
    except Exception:  # the coach must never fail a sync – the data is already stored
        log.exception("planning today's workout failed")
        console.print("[yellow]Planning today's workout failed[/] (details in the log).")
        return
    console.print(f"Today: {escape(row.name)}")


@app.command()
def backfill(
    months: int = typer.Option(24, "--months", min=1, help="Calendar months to download."),
    restart: bool = typer.Option(
        False, "--restart", help="Walk the whole range again (picks up activities edited later)."
    ),
) -> None:
    """First-run history download, month by month backwards. Resumable: just run it again."""
    with _garmin_session() as (session, client):
        result = run_backfill(
            session,
            client,
            months,
            dt.date.today(),
            restart=restart,
            on_month=lambda cursor: console.print(f"  month done, next: {cursor:%Y-%m}"),
        )
        _report(result)
        _after_ingest(session, result)


@app.command("db-stats")
def db_stats() -> None:
    """Row counts per table and raw payloads per kind."""
    engine = get_engine(get_settings())
    with Session(engine) as session:
        counts, raw = repo.table_counts(session), repo.raw_counts_by_kind(session)
        state = {
            k: repo.get_state(session, k)
            for k in ("last_activity_sync", "last_wellness_date", "backfill_cursor")
        }
        queues = {
            k: len(repo.get_state_json(session, k) or {})
            for k in (PENDING_ACTIVITIES, PENDING_WELLNESS, FAILED_ACTIVITIES, FAILED_WELLNESS)
        }
        failed_ids = sorted(repo.get_state_json(session, FAILED_ACTIVITIES) or {})
    table = Table("table", "rows")
    for name, n in counts.items():
        table.add_row(name, f"{n:,}")
    console.print(table)
    if raw:
        kinds = Table("raw kind", "payloads")
        for kind, n in raw.items():
            kinds.add_row(kind, f"{n:,}")
        console.print(kinds)
    for key, value in state.items():
        console.print(f"{key}: {value or '–'}")
    for key, n in queues.items():
        console.print(f"{key}: {n}")
    if failed_ids:
        console.print(f"failed activity ids: {', '.join(failed_ids[:20])}")
