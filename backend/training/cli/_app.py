"""Shared Typer app and consoles for the `training` CLI."""

import typer
from rich.console import Console

from training import log_redaction

app = typer.Typer(
    help="Personal training analytics (Garmin Connect → metrics → coach).",
    no_args_is_help=True,
    pretty_exceptions_show_locals=False,  # never render locals (the password) in a traceback
)
console = Console(soft_wrap=True)
err = Console(stderr=True, soft_wrap=True)


@app.callback()
def main(verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug logging.")) -> None:
    log_redaction.setup_logging(verbose)  # quiet third-party loggers, credentials redacted from every line
