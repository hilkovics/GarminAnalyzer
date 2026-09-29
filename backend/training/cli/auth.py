"""`training login` / `training whoami`."""

import typer
from rich.markup import escape

from training.cli._app import app, console, err
from training.config import get_settings
from training.garmin import client as garmin_client


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
