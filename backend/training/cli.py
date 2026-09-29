"""`training` command line (Typer). Commands are thin wrappers; logic lives in the core packages.

Phase 0: `login`, `whoami`. Phase 1: `sync`, `backfill`, `db-stats`. Later phases add recompute, api, …
"""

import datetime as dt
import logging
from collections.abc import Iterator
from contextlib import contextmanager

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table
from sqlmodel import Session

from training.config import get_settings
from training.db import repo
from training.db.session import get_engine
from training.garmin import client as garmin_client
from training.garmin.backfill import backfill as run_backfill
from training.garmin.sync import SyncResult, raw_sink_for
from training.garmin.sync import sync as run_sync

app = typer.Typer(
    help="Personal training analytics (Garmin Connect → metrics → coach).",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,  # never render locals (the password) in a traceback
)
console = Console(soft_wrap=True)
err = Console(stderr=True, soft_wrap=True)


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging.")) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # garminconnect/urllib3 debug output can include request details; keep it quiet unless asked.
    for name in ("garminconnect", "urllib3", "curl_cffi"):
        logging.getLogger(name).setLevel(logging.DEBUG if verbose else logging.WARNING)


def _prompt_mfa() -> str:
    return typer.prompt("MFA code").strip()


@app.command()
def login(
    email: str | None = typer.Option(None, "--email", help="Garmin account e-mail (prompted if omitted)."),
    force: bool = typer.Option(False, "--force", help="Discard stored tokens and log in again."),
) -> None:
    """Interactive Garmin Connect login (with MFA prompt). Stores tokens only – never the password."""
    settings = get_settings()
    tokens_dir = settings.tokens_dir
    if not force and garmin_client.token_file(tokens_dir).exists():
        try:
            api = garmin_client.connect(tokens_dir)
            console.print(f"[green]Already logged in[/] as {api.get_full_name() or api.display_name}.")
            console.print(f"Tokens: {garmin_client.token_file(tokens_dir)} (use --force to log in again)")
            return
        except garmin_client.GarminConnectAuthenticationError:
            console.print("[yellow]Stored tokens are no longer valid – logging in again.[/]")

    email = email or typer.prompt("Garmin e-mail")
    password = typer.prompt("Garmin password", hide_input=True)
    try:
        api = garmin_client.login_interactive(email, password, _prompt_mfa, tokens_dir, force=force)
    except garmin_client.GarminConnectAuthenticationError as exc:
        err.print(f"[red]Login failed:[/] {escape(str(exc))}")
        raise typer.Exit(1) from None
    except garmin_client.GarminConnectTooManyRequestsError:
        err.print("[red]Garmin is rate-limiting logins (429).[/] Wait a while and try again.")
        raise typer.Exit(1) from None
    except garmin_client.GarminConnectConnectionError as exc:
        err.print(f"[red]Could not reach Garmin Connect:[/] {type(exc).__name__}")
        raise typer.Exit(1) from None
    except (OSError, ValueError) as exc:
        err.print(f"[red]Could not store tokens in {escape(str(tokens_dir))}:[/] {type(exc).__name__}")
        raise typer.Exit(1) from None
    finally:
        del password
    console.print(f"[green]Logged in[/] as {api.get_full_name() or api.display_name}.")
    console.print(f"Tokens stored in {garmin_client.token_file(tokens_dir)}")


@app.command()
def whoami() -> None:
    """Verify the stored tokens by fetching the Garmin profile."""
    settings = get_settings()
    try:
        api = garmin_client.connect(settings.tokens_dir)
    except garmin_client.GarminConnectAuthenticationError as exc:
        err.print(f"[red]Not logged in:[/] {escape(str(exc))}")
        raise typer.Exit(1) from None
    except garmin_client.GarminConnectConnectionError as exc:
        err.print(f"[red]Could not reach Garmin Connect:[/] {type(exc).__name__}")
        raise typer.Exit(1) from None
    console.print(api.get_full_name() or api.display_name)


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
        except KeyboardInterrupt:
            err.print("[yellow]Interrupted.[/] Progress is saved – run the same command again to continue.")
            raise typer.Exit(130) from None


def _report(result: SyncResult) -> None:
    console.print(
        f"Activities: [green]{result.activities_new} new[/], {result.activities_updated} updated, "
        f"{result.activities_unchanged} unchanged · wellness days: {result.wellness_days}"
    )
    if result.errors:
        console.print(f"[yellow]{len(result.errors)} endpoint calls failed[/] (details in the log):")
        for line in result.errors[:10]:
            console.print(f"  - {escape(line)}")
        if len(result.errors) > 10:
            console.print(f"  … and {len(result.errors) - 10} more")


@app.command()
def sync() -> None:
    """Incremental sync of activities and wellness (idempotent; safe to run from cron)."""
    with _garmin_session() as (session, client):
        _report(run_sync(session, client, dt.date.today()))


@app.command()
def backfill(months: int = typer.Option(24, "--months", min=1, help="Calendar months to download.")) -> None:
    """First-run history download, month by month backwards. Resumable: just run it again."""
    with _garmin_session() as (session, client):
        result = run_backfill(
            session,
            client,
            months,
            dt.date.today(),
            on_month=lambda cursor: console.print(f"  month done, next: {cursor:%Y-%m}"),
        )
        _report(result)


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


if __name__ == "__main__":
    app()
