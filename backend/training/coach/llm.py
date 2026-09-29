"""Optional weekly LLM report built from DTOs only; never changes the plan (phase 7).

This module only turns `WeeklyReportInputsDTO` into a prompt and the model's answer into text: no database, no
plan writes. The `anthropic` SDK is the optional extra `ai` and is imported lazily, so the core works without
it. Errors are reported as `ReportError` with a short message that never contains the API key.
"""

import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from training.services.dto import (
    CorrelationDTO,
    ReportPmcDTO,
    WeeklyReportInputsDTO,
    WeekPlanDTO,
)

BETAS = ["server-side-fallback-2026-07-01"]
MAX_TOKENS = 4000
MISSING = "chýba"

SYSTEM_PROMPT = """\
Si tréner vytrvalostného bežca a cyklistu. Vysvetli jeho uplynulý týždeň a nasledujúci plán po \
slovensky, najviac 250 slovami.

Pravidlá:
- Používaj iba údaje z používateľovej správy. Plán (cieľové záťaže, tréningy, dátumy) nikdy nemeň, \
nevymýšľaj a neprepočítavaj; iba ho vysvetľuj.
- Ak údaj chýba (v správe je "chýba"), povedz to otvorene a nedomýšľaj si ho.
- Nedávaj lekárske rady ani diagnózy. Pri únave či bolesti odporuč poradiť sa s lekárom alebo trénerom.
- Zistenia o spánku sú korelácie, nie dôkaz príčiny; uveď to stručne.
- Výstup je Markdown s presne 3 krátkymi sekciami: "## Uplynulý týždeň", "## Kondícia a regenerácia", \
"## Plán na ďalší týždeň".
"""


class ReportError(Exception):
    """The report could not be generated (refusal, invalid key, rate limit, network, empty answer)."""


# --- prompt ---------------------------------------------------------------------------------------------


def _n(value: float | None, digits: int = 0, sign: bool = False) -> str:
    if value is None:
        return MISSING
    return f"{value:+.{digits}f}" if sign else f"{value:.{digits}f}"


def _min(seconds: float | None) -> str:
    return MISSING if seconds is None else f"{round(seconds / 60)} min"


def _pmc(label: str, point: ReportPmcDTO | None) -> str:
    if point is None:
        return f"- {label}: {MISSING}"
    return (
        f"- {label} ({point.date}): CTL {_n(point.ctl, 1)}, ATL {_n(point.atl, 1)}, "
        f"TSB {_n(point.tsb, 1, True)}, nárast CTL/týždeň {_n(point.ramp_rate, 1, True)}"
    )


def _finding(f: CorrelationDTO) -> str:
    """The headline ρ (partial when present, as on the Spánok page) with its own CI."""
    partial = f.partial_rho is not None
    low, high = (f.partial_ci_low, f.partial_ci_high) if partial else (f.ci_low, f.ci_high)
    label = "parciálne ρ" if partial else "ρ"
    ci = f"95 % CI {_n(low, 2)} až {_n(high, 2)}"
    return f"- {f.sentence} ({label} = {_n(f.headline_rho, 2)}, {ci}, n = {f.n})"


def _week(title: str, week: WeekPlanDTO) -> list[str]:
    lines = [
        f"{title} (od {week.monday}, fáza {week.phase}{', regeneračný' if week.recovery else ''}): "
        f"cieľová záťaž {week.target_load:.0f} (beh {week.run_target:.0f}, bicykel {week.bike_target:.0f}), "
        f"hotovo {week.done_load:.0f}, zostáva {week.remaining_load:.0f}"
    ]
    for day in week.days:
        planned = day.planned
        if planned is None:
            lines.append(f"- {day.date} ({day.weekday}): bez plánu, skutočná záťaž {day.actual_load:.0f}")
            continue
        load = f", odhad záťaže {planned.estimated_load:.0f}" if planned.estimated_load is not None else ""
        lines.append(
            f"- {day.date} ({day.weekday}): {planned.name} [{planned.sport}, {_min(planned.duration_s)}"
            f"{load}, stav {planned.status}], skutočná záťaž {day.actual_load:.0f}"
        )
    return lines


def _goal(inputs: WeeklyReportInputsDTO) -> str:
    goal = inputs.goal
    if goal is None:
        return f"Cieľ: {MISSING} (bez cieľových pretekov)"
    distance = f"{goal.distance_m / 1000:g} km" if goal.distance_m else MISSING
    target = _min(goal.target_time_s) if goal.target_time_s else MISSING
    return f"Cieľ: {goal.sport}, preteky {goal.race_date}, vzdialenosť {distance}, cieľový čas {target}"


def build_weekly_prompt(inputs: WeeklyReportInputsDTO) -> tuple[str, str]:
    """(system, user) prompt of the weekly report. Pure: numbers come from the DTOs, nothing is computed."""
    lines = [f"Dnes je {inputs.today}.", "", "## Posledných 7 dní – aktivity (dátum, šport, trvanie, záťaž)"]
    if inputs.activities:
        lines += [
            f"- {a.date}: {a.sport}, {_min(a.duration_s)}, záťaž {_n(a.load)}" for a in inputs.activities
        ]
    else:
        lines.append("- žiadne aktivity")
    lines += [
        "",
        "## Kondícia (PMC)",
        _pmc("teraz", inputs.pmc_now),
        _pmc("pred 7 dňami", inputs.pmc_week_ago),
    ]
    lines += ["", "## Pripravenosť (0–100) za posledných 7 dní"]
    lines += [
        f"- {r.date}: {_n(r.score)}" + (f" ({r.band})" if r.band else "") for r in inputs.readiness
    ] or [f"- {MISSING}"]
    lines += ["", "## Najsilnejšie zistenia o spánku"]
    lines += [_finding(f) for f in inputs.findings] or [f"- {MISSING} (málo dát)"]
    lines += ["", "## Plán", *_week("Tento týždeň", inputs.this_week), ""]
    lines += _week("Budúci týždeň", inputs.next_week)
    lines += ["", _goal(inputs)]
    return SYSTEM_PROMPT, "\n".join(lines)


# --- API call ---------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class GeneratedReport:
    text: str
    model: str  # the model that answered (`response.model`)


def generate_weekly_report(
    inputs: WeeklyReportInputsDTO,
    *,
    api_key: str,
    model: str,
    client_factory: Callable[[str], Any] | None = None,
) -> GeneratedReport:
    """Ask the model for the report; its Markdown and the model that wrote it (a server-side fallback may
    answer instead of `model`). Raises `ReportError` (never with the key)."""
    try:
        import anthropic
    except ImportError:  # the optional extra is missing (review phase 7)
        raise ReportError("the AI report needs the optional extra: uv sync --extra ai") from None

    system, user = build_weekly_prompt(inputs)
    try:
        client = (client_factory or (lambda key: anthropic.Anthropic(api_key=key)))(api_key)
        response = client.beta.messages.create(
            model=model,
            max_tokens=MAX_TOKENS,
            betas=BETAS,
            fallbacks="default",
            output_config={"effort": "medium"},
            system=system,
            messages=[{"role": "user", "content": user}],
        )
    except anthropic.AuthenticationError:
        raise ReportError("invalid key (authentication with the Anthropic API failed)") from None
    except anthropic.RateLimitError:
        raise ReportError("rate limit reached, try again later") from None
    except anthropic.APIStatusError as exc:
        raise ReportError(f"Anthropic API error (HTTP {exc.status_code})") from None
    except anthropic.APIConnectionError:
        raise ReportError("cannot reach the Anthropic API (connection error)") from None
    if response.stop_reason == "refusal":
        raise ReportError("the model refused to write the report")
    if response.stop_reason == "max_tokens":
        raise ReportError("the report was cut off (max_tokens) – not stored")
    text = "".join(block.text for block in response.content if block.type == "text").strip()
    if not text:
        raise ReportError("the model returned no text")
    return GeneratedReport(text=text, model=str(getattr(response, "model", None) or model))


def week_label(day: dt.date) -> str:
    """ISO week label "YYYY-Www" of the week the report looks back on: the week of `day − 1`, so a run on
    Sunday evening or Monday morning (the intended schedule) both name the week that just ended."""
    year, week, _ = (day - dt.timedelta(days=1)).isocalendar()
    return f"{year}-W{week:02d}"
