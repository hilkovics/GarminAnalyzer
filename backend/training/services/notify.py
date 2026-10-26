"""Telegram morning message (phase 7): readiness, today's workout and yesterday's load in one plain text.

Built from the existing services only. Sending is best-effort and never raises: any failure is logged as an
error class and an HTTP status code – never the token, the URL (it contains the token) or the exception text
(`requests` puts the URL into it). Durations are written as whole minutes, this text being presentation.
"""

import datetime as dt
import logging
import time
from typing import Any

import requests
from sqlmodel import Session

from training.config import Settings
from training.services import fitness, forecast, plan, sleep
from training.services.dto import MorningMessageDTO, WorkoutStepDTO

log = logging.getLogger(__name__)

API_URL = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT_S = 10
ATTEMPTS = 2  # one retry on 5xx / timeouts
RETRY_DELAY_S = 1.0
MAX_TEXT = 4096  # Telegram's limit for one message

BAND_WORDS = {"green": "zelená", "yellow": "žltá", "red": "červená"}
COMPONENT_WORDS = {
    "rhr": "pokojový tep",
    "sleep": "spánok",
    "body_battery": "Body Battery",
    "form": "forma",
}
SPORT_WORDS = {"run": "beh", "bike": "bicykel"}
WEEKDAY_WORDS = ("po", "ut", "st", "št", "pi", "so", "ne")
STEP_WORDS = {
    "warmup": "Rozcvička",
    "work": "Záťaž",
    "recovery": "Oddych",
    "cooldown": "Vychladenie",
    "steady": "Rovnomerne",
}


def _minutes(seconds: float) -> str:
    return f"{round(seconds / 60)} min"


def _short(step: WorkoutStepDTO) -> str:
    kind = "úsilie Z" if step.target_kind == "open" else "Z"
    return f"{_minutes(step.duration_s)} {kind}{step.zone}"


def step_summary(steps: list[WorkoutStepDTO]) -> str:
    """Compact steps: "Rozcvička 15 min Z2; 5× (6 min Z4 / 2 min Z1); Vychladenie 10 min Z1"."""
    parts: list[str] = []
    seen: set[int] = set()
    for step in steps:
        if step.group is None:
            parts.append(f"{STEP_WORDS.get(step.type, step.type)} {_short(step)}")
        elif step.group not in seen:
            seen.add(step.group)
            body = " / ".join(_short(s) for s in steps if s.group == step.group)
            parts.append(f"{step.repeat}× ({body})")
    return "; ".join(parts)


def _readiness_line(session: Session, today: dt.date) -> tuple[str, float | None, str | None]:
    result = sleep.get_readiness(session, today)
    if not result.available or result.score is None:
        return "Pripravenosť: nedostatok wellness dát.", None, None
    line = f"Pripravenosť: {int(result.score)}/100 ({BAND_WORDS.get(result.band or '', result.band)})"
    missing = [COMPONENT_WORDS.get(c.name, c.name) for c in result.components if c.score is None]
    if missing:
        line += f", chýba: {', '.join(missing)}"
    return line + f". {result.message}", result.score, result.band


def _forecast_lines(session: Session, today: dt.date) -> list[str]:
    """§11.5: the sleep note and the best days for quality (none when there is nothing reliable to say)."""
    result = forecast.get_forecast(session, today)
    lines = [result.note.text] if result.note else []
    best = [d.date for d in result.days if d.best]
    if best:
        names = ", ".join(f"{WEEKDAY_WORDS[d.weekday()]} {d.day}. {d.month}." for d in best)
        lines.append(f"Výhľad: najlepšie dni na kvalitný tréning – {names}")
    return lines


def morning_message(session: Session, today: dt.date) -> MorningMessageDTO:
    """The morning text of `today` (METRICS §8 readiness, §10/§11 plan, §11.5 note, §4 load); ≤ 10 lines."""
    readiness_line, score, band = _readiness_line(session, today)
    decision = plan.get_today(session, today)
    workout = decision.workout
    lines = [f"Dobré ráno, {today.day}. {today.month}.", readiness_line]
    if workout.sport == "rest":
        lines.append(f"Dnes: {workout.name} (voľno).")
    else:
        sport = SPORT_WORDS.get(workout.sport, workout.sport)
        load = f", záťaž ~{workout.estimated_load:.0f}" if workout.estimated_load is not None else ""
        lines.append(f"Dnes: {workout.name} ({sport}, {_minutes(workout.duration_s)}{load}).")
        if workout.provisional:  # decided before today's sync – may still change (review phase 8, W4)
            lines.append("Plán je predbežný – po synchronizácii sa môže zmeniť.")
    if decision.reason:
        lines.append(f"Prečo: {decision.reason}")
    if workout.steps:
        lines.append(f"Kroky: {step_summary(workout.steps)}")
    try:  # orientation only: a failure here must never cost the whole message (review step 3, W3)
        lines.extend(_forecast_lines(session, today))
    except Exception as exc:
        log.warning("morning message: forecast lines skipped (%s)", type(exc).__name__)
    yesterday = today - dt.timedelta(days=1)
    point = fitness.get_pmc(session, date_from=yesterday, date_to=yesterday).latest
    if point is None:
        lines.append("Včera: bez dát o záťaži.")
        load_y, tsb = None, None
    else:
        load_y, tsb = point.load_total, point.tsb
        tsb_text = f"{tsb:+.0f}" if tsb is not None else "–"
        lines.append(f"Včera: záťaž {load_y:.0f}, TSB {tsb_text}.")
    return MorningMessageDTO(
        date=today,
        text="\n".join(lines)[:MAX_TEXT],
        readiness=score,
        readiness_band=band,
        workout_name=workout.name,
        yesterday_load=load_y,
        tsb=tsb,
    )


def is_configured(settings: Settings) -> bool:
    return bool(
        settings.telegram_token and settings.telegram_token.get_secret_value() and settings.telegram_chat_id
    )


def _post(http: Any, token: str, chat_id: str, text: str) -> bool:
    """POST with one retry on 5xx / timeout / connection error; logs class and status code only."""
    for attempt in range(ATTEMPTS):
        status: int | None = None
        error: str | None = None
        try:
            response = http.post(
                API_URL.format(token=token),
                json={"chat_id": chat_id, "text": text},
                timeout=TIMEOUT_S,
            )
            status = int(response.status_code)
            if 200 <= status < 300:
                return True
            error = "HTTPStatus"
            retry = status >= 500
        except (requests.Timeout, requests.ConnectionError) as exc:
            error, retry = type(exc).__name__, True
        except Exception as exc:
            error, retry = type(exc).__name__, False
        log.warning("telegram send failed: %s status=%s (attempt %d)", error, status, attempt + 1)
        if not retry:
            return False
        if attempt + 1 < ATTEMPTS:
            time.sleep(RETRY_DELAY_S)
    return False


def send_morning(session: Session, today: dt.date, settings: Settings, *, http: Any = requests) -> bool:
    """Send the morning message; True when Telegram accepted it. False when unconfigured (no network call)
    or on any failure. Never raises."""
    if not is_configured(settings):
        log.info("telegram not configured, morning message skipped")
        return False
    try:
        assert settings.telegram_token is not None and settings.telegram_chat_id is not None
        text = morning_message(session, today).text
        return _post(http, settings.telegram_token.get_secret_value(), settings.telegram_chat_id, text)
    except Exception as exc:
        log.warning("telegram morning message failed: %s", type(exc).__name__)
        return False
