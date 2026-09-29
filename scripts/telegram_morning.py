"""Send the Telegram morning message (cron entry point, same as `uv run training telegram-morning`).

    uv run python scripts/telegram_morning.py [--dry-run]

Needs TRAINING_TELEGRAM_TOKEN and TRAINING_TELEGRAM_CHAT_ID; without them nothing is sent. A Telegram outage
never makes this fail.
"""

import typer

from training import log_redaction
from training.cli.notify import telegram_morning

if __name__ == "__main__":
    log_redaction.setup_logging()  # typer.run skips the CLI callback: same logging + token redaction
    typer.run(telegram_morning)
