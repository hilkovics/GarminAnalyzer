"""Send the Telegram morning message (cron entry point, same as `uv run training telegram-morning`).

    uv run python scripts/telegram_morning.py [--dry-run]

Needs TRAINING_TELEGRAM_TOKEN and TRAINING_TELEGRAM_CHAT_ID; without them nothing is sent. A Telegram outage
never makes this fail.
"""

import typer

from training.cli.notify import telegram_morning

if __name__ == "__main__":
    typer.run(telegram_morning)
