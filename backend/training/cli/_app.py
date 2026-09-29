"""Shared Typer app and consoles for the `training` CLI."""

import logging

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
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # garminconnect/urllib3 debug output can include request details; keep it quiet unless asked, and
    # redact credentials (e.g. the Telegram token in a request URL) from every line either way.
    for name in ("garminconnect", "urllib3", "curl_cffi", "alembic"):
        logging.getLogger(name).setLevel(logging.DEBUG if verbose else logging.WARNING)
    log_redaction.install()
