"""Formatting helpers – the only place where internal units become display strings.

Internal units are seconds, metres, m/s (CLAUDE.md conventions). Everything here is presentation: m/s →
"m:ss/km", seconds → "h:mm", metres → km. `None` always renders as an en dash. Numbers follow the Slovak
convention of the design: decimal comma ("12,3 km") and a real minus sign ("−6,3"). No Streamlit or Plotly
imports, so the helpers are trivial to test.
"""

import datetime as dt
import math
import re

DASH = "–"
MINUS = "−"  # U+2212, not a hyphen

SPORT_LABELS = {"run": "Beh", "bike": "Bicykel", "other": "Iné", "all": "Spolu"}
LOAD_METHOD_LABELS = {"hrtss": "hrTSS", "rtss": "rTSS", "trimp": "TRIMP"}
THRESHOLD_SOURCE_LABELS = {"manual": "ručne", "proposal": "návrh"}

# Bounds for a threshold pace typed by the user (input sanity check, not a training rule).
_MIN_PACE_S = 120  # 2:00 /km
_MAX_PACE_S = 900  # 15:00 /km


def _valid(x: float | None) -> bool:
    return x is not None and not math.isnan(x)


def sport_label(sport: str | None) -> str:
    if sport is None:
        return DASH
    return SPORT_LABELS.get(sport, sport)


def load_method_label(method: str | None) -> str:
    """Load method code → display name ("hrtss" → "hrTSS"); unknown codes pass through."""
    return DASH if method is None else LOAD_METHOD_LABELS.get(method, method)


def threshold_source_label(source: str | None) -> str:
    """Threshold source code → Slovak label ("manual" → "ručne", "proposal" → "návrh")."""
    return DASH if source is None else THRESHOLD_SOURCE_LABELS.get(source, source)


def decimal_comma(text: str) -> str:
    """Python number text → Slovak: "." becomes "," and a leading/inner "-" before a digit becomes "−"."""
    return re.sub(r"(?<![\w.])-(?=\d)", MINUS, text).replace(".", ",")


def _no_negative_zero(x: float, digits: int) -> float:
    """-0.04 at one decimal would print as "−0,0"; show it as 0."""
    return 0.0 if round(x, digits) == 0 else x


def fmt_num(x: float | None, digits: int = 0, unit: str = "") -> str:
    """Plain number with a fixed number of decimals and an optional unit; None → "–"."""
    if not _valid(x):
        return DASH
    text = decimal_comma(f"{_no_negative_zero(x, digits):.{digits}f}")
    return f"{text} {unit}".strip() if unit else text


def fmt_signed(x: float | None, digits: int = 1) -> str:
    """Number with an explicit sign (TSB, ramp rate); None → "–"."""
    if not _valid(x):
        return DASH
    return decimal_comma(f"{_no_negative_zero(x, digits):+.{digits}f}")


def fmt_pct_signed(share: float | None, digits: int = 1) -> str:
    """Fraction (0–1) → signed percent string "+1,2 %"; None → "–"."""
    if not _valid(share):
        return DASH
    return decimal_comma(f"{share * 100:+.{digits}f} %")


def fmt_pct(share: float | None, digits: int = 0) -> str:
    """Fraction (0–1) → percent string."""
    if not _valid(share):
        return DASH
    return decimal_comma(f"{share * 100:.{digits}f} %")


def fmt_pace_s(seconds_per_km: float) -> str:
    """Seconds per km → "m:ss" (no unit; also used for chart ticks)."""
    minutes, secs = divmod(int(seconds_per_km + 0.5), 60)
    return f"{minutes}:{secs:02d}"


def fmt_pace(speed_ms: float | None) -> str:
    """m/s → "m:ss/km" (rounded to a whole second); None, 0 or negative → "–"."""
    if not _valid(speed_ms) or speed_ms <= 0:
        return DASH
    return f"{fmt_pace_s(1000.0 / speed_ms)}/km"


def fmt_speed_kmh(speed_ms: float | None) -> str:
    """m/s → "x,x km/h"; None or negative → "–"."""
    if not _valid(speed_ms) or speed_ms < 0:
        return DASH
    return decimal_comma(f"{speed_ms * 3.6:.1f} km/h")


def fmt_speed(speed_ms: float | None, sport: str | None) -> str:
    """Pace for running (and anything that is not a bike), km/h for cycling."""
    return fmt_speed_kmh(speed_ms) if sport == "bike" else fmt_pace(speed_ms)


def fmt_duration(seconds: float | None) -> str:
    """Seconds → "h:mm" (rounded to the nearest minute); None or negative → "–"."""
    if not _valid(seconds) or seconds < 0:
        return DASH
    hours, mins = divmod(int(seconds / 60 + 0.5), 60)
    return f"{hours}:{mins:02d}"


def fmt_duration_hms(seconds: float | None) -> str:
    """Seconds → "m:ss" below one hour, "h:mm:ss" from one hour (laps); None or negative → "–"."""
    if not _valid(seconds) or seconds < 0:
        return DASH
    hours, rest = divmod(int(seconds + 0.5), 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def fmt_km(metres: float | None, digits: int = 1) -> str:
    """Metres → "12,3 km"; None or negative → "–"."""
    if not _valid(metres) or metres < 0:
        return DASH
    return decimal_comma(f"{metres / 1000.0:.{digits}f} km")


def fmt_hours(seconds: float | None, digits: int = 1) -> str:
    """Seconds → decimal hours "3,5 h"."""
    if not _valid(seconds) or seconds < 0:
        return DASH
    return decimal_comma(f"{seconds / 3600.0:.{digits}f} h")


def fmt_date(d: dt.date | None) -> str:
    """Date → "29. 09. 2026"."""
    if d is None:
        return DASH
    return f"{d.day:02d}. {d.month:02d}. {d.year}"


def fmt_datetime(moment: dt.datetime | None, sep: str = " ") -> str:
    """Timestamp → local "23. 10. 2026 6:01" (`sep` between date and time); None → "–".

    Converted with `astimezone()`, i.e. to the system local zone; a naive value is taken as local already.
    """
    if moment is None:
        return DASH
    local = moment.astimezone()
    return f"{local.day}. {local.month}. {local.year}{sep}{local.hour}:{local.minute:02d}"


def fmt_load(load: float | None, method: str | None = None, *, low_confidence: bool = False) -> str:
    """Training load "87 (hrTSS)"; a null load is "neznáma" (METRICS §2.1: unknown, not zero).

    Unknown or low-confidence loads carry the warning marker "⚠".
    """
    unknown = not _valid(load)
    text = "neznáma" if unknown else f"{load:.0f}" + (f" ({load_method_label(method)})" if method else "")
    return f"⚠ {text}" if unknown or low_confidence else text


def fmt_zone_range(lower: float | None, upper: float | None, kind: str = "hr") -> str:
    """Zone bounds → "130–150 bpm" (kind "hr") or "5:30–4:50/km" (kind "pace", bounds are m/s).

    A pace zone's lower bound is the slower speed, so the range reads slow–fast.
    """
    if kind == "pace":
        if not _valid(lower) or lower <= 0:
            return DASH if not _valid(upper) else f"pomalšie ako {fmt_pace(upper)}"
        if not _valid(upper):
            return f"rýchlejšie ako {fmt_pace(lower)}"
        return f"{fmt_pace_s(1000.0 / lower)}–{fmt_pace(upper)}"
    if not _valid(lower) and not _valid(upper):
        return DASH
    if not _valid(lower):
        return f"< {upper:.0f} bpm"
    if not _valid(upper):
        return f"> {lower:.0f} bpm"
    return f"{lower:.0f}–{upper:.0f} bpm"


def parse_pace(text: str) -> float:
    """Parse "m:ss" (optionally "m:ss/km") into m/s. Raises ValueError with a Slovak message."""
    raw = (text or "").strip().lower().removesuffix("/km").strip()
    parts = [p.strip() for p in raw.split(":")]
    if len(parts) != 2 or not all(p.isascii() and p.isdigit() for p in parts):
        raise ValueError("Tempo zadaj ako m:ss, napr. 4:10.")
    minutes, secs = int(parts[0]), int(parts[1])
    if secs >= 60:
        raise ValueError("Sekundy musia byť v rozsahu 0–59.")
    total = minutes * 60 + secs
    if not _MIN_PACE_S <= total <= _MAX_PACE_S:
        raise ValueError("Tempo musí byť medzi 2:00 a 15:00 min/km.")
    return 1000.0 / total


def fmt_window(seconds: int | float | None) -> str:
    """Best-effort window length → "5 min" (whole minutes) or "45 s"; None → "–"."""
    if not _valid(seconds) or seconds <= 0:
        return DASH
    return f"{int(seconds) // 60} min" if seconds % 60 == 0 else f"{int(seconds)} s"


def fmt_time_hms(seconds: float | None) -> str:
    """Race time → "h:mm:ss" (always with hours, e.g. "0:19:58"); None or negative → "–"."""
    if not _valid(seconds) or seconds < 0:
        return DASH
    hours, rest = divmod(int(seconds + 0.5), 3600)
    minutes, secs = divmod(rest, 60)
    return f"{hours}:{minutes:02d}:{secs:02d}"


def fmt_rho(rho: float | None, low: float | None = None, high: float | None = None, digits: int = 2) -> str:
    """Correlation "+0,35" or with its interval "+0,35 [95 % CI −0,10; +0,55]"; None → "–"."""
    if not _valid(rho):
        return DASH
    text = f"{rho:+.{digits}f}"
    if _valid(low) and _valid(high):
        text += f" [95 % CI {low:+.{digits}f}; {high:+.{digits}f}]"
    return decimal_comma(text)


def parse_time_hms(text: str) -> float | None:
    """Parse a target time "h:mm:ss" (or "m:ss") into seconds; blank → None. Raises ValueError (Slovak)."""
    raw = (text or "").strip()
    if not raw:
        return None
    parts = [p.strip() for p in raw.split(":")]
    if len(parts) not in (2, 3) or not all(p.isascii() and p.isdigit() for p in parts):
        raise ValueError("Cieľový čas zadaj ako h:mm:ss, napr. 0:40:00.")
    *head, minutes, secs = (int(p) for p in parts)
    if minutes >= 60 or secs >= 60:
        raise ValueError("Minúty a sekundy musia byť v rozsahu 0–59.")
    total = (head[0] if head else 0) * 3600 + minutes * 60 + secs
    if total <= 0:
        raise ValueError("Cieľový čas musí byť kladný.")
    return float(total)
