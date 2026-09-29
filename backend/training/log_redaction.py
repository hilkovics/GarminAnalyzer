"""Redact credentials from every log line (CLAUDE.md rule 8), including third-party DEBUG output.

urllib3 logs each request line at DEBUG (`"POST /bot<token>/sendMessage HTTP/1.1"`), so a Telegram token in
the URL path would reach the log with `training -v` (review phase 7 B1). `install()` adds a filter to every
root handler that rewrites the formatted message before it is emitted.
"""

import logging
import re

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
