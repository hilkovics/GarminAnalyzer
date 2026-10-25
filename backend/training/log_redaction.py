"""Redact credentials from every log line (CLAUDE.md rule 8), including third-party DEBUG output.

urllib3 logs each request line at DEBUG (`"POST /bot<token>/sendMessage HTTP/1.1"`), so a Telegram token in
the URL path would reach the log with `training -v` (review phase 7 B1). `install()` adds a filter to every
root handler that rewrites the formatted message before it is emitted.
"""

import json
import logging
import logging.handlers
import re
from pathlib import Path

PATTERNS = (
    (re.compile(r"bot\d+:[A-Za-z0-9_-]+"), "bot<redacted>"),  # Telegram bot token in a URL
    (re.compile(r"sk-ant-[A-Za-z0-9_-]+"), "sk-ant-<redacted>"),  # Anthropic API key
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]+"), r"\1<redacted>"),  # Authorization headers
)


def redact(text: str) -> str:
    for pattern, replacement in PATTERNS:
        text = pattern.sub(replacement, text)
    return text


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = redact(message)
        if cleaned != message:
            record.msg, record.args = cleaned, None
        return True


def install(logger: logging.Logger | None = None) -> None:
    """Attach the filter to every handler of `logger` (default: root); idempotent."""
    target = logger or logging.getLogger()
    for handler in target.handlers:
        if not any(isinstance(f, RedactingFilter) for f in handler.filters):
            handler.addFilter(RedactingFilter())


QUIET_LOGGERS = ("garminconnect", "urllib3", "curl_cffi", "alembic")


def setup_logging(verbose: bool = False) -> None:
    """The one logging setup of every entry point (CLI callback and the cron scripts)."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # garminconnect/urllib3 debug output can include request details; quiet unless asked, redacted always
    for name in QUIET_LOGGERS:
        logging.getLogger(name).setLevel(logging.DEBUG if verbose else logging.WARNING)
    install()


LOG_FILE = "training.log"  # JSON lines, rotated at 5 MB, 10 files kept
STRUCTURED_FIELDS = ("step", "status", "duration_s", "run_ok")


class JsonFormatter(logging.Formatter):
    """One JSON object per line: ts, level, logger, msg (+ the morning run's step fields, + exc type)."""

    def format(self, record: logging.LogRecord) -> str:
        out: dict[str, object] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": redact(record.getMessage()),
        }
        for key in STRUCTURED_FIELDS:
            if hasattr(record, key):
                out[key] = getattr(record, key)
        if record.exc_info:
            out["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(out, ensure_ascii=False)


def add_file_handler(log_dir: Path) -> Path:
    """Structured log file under `log_dir` (phase 8, `training morning`); idempotent. Returns its path."""
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / LOG_FILE
    root = logging.getLogger()
    for handler in root.handlers:
        if isinstance(handler, logging.FileHandler) and Path(handler.baseFilename) == path.resolve():
            return path
    handler = logging.handlers.RotatingFileHandler(path, maxBytes=5_000_000, backupCount=10, encoding="utf-8")
    handler.setFormatter(JsonFormatter())
    handler.addFilter(RedactingFilter())
    root.addHandler(handler)
    return path
