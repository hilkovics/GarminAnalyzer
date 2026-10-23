"""HTML snippets for the small label / value pairs and titles of the cards (classes live in `_style.py`).

String in, string out – every value is escaped, so DTO text can be passed straight through.
"""

from html import escape


def meta_html(label: str, value: str) -> str:
    """Small caps label above a number-font value, e.g. ŠPORT / Bicykel."""
    return f'<div class="ka-label">{escape(label)}</div><div class="ka-value">{escape(value)}</div>'


def title_html(text: str) -> str:
    """Large card title (workout name)."""
    return f'<div class="ka-title">{escape(text)}</div>'
