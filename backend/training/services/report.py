"""Weekly AI report service (phase 7): gather DTOs, ask the model, store `reports_dir/YYYY-Www.md`.

The LLM (`training.coach.llm`) only explains the plan; nothing here writes to the database. Needs
TRAINING_ANTHROPIC_API_KEY (`InvalidInputError` otherwise). Pages never call the API, they read the file.
"""

import datetime as dt
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

from sqlmodel import Session

from training.coach import llm
from training.config import Settings
from training.services import activities, fitness, plan, sleep
from training.services.dto import (
    ReportActivityDTO,
    ReportDTO,
    ReportPmcDTO,
    ReportReadinessDTO,
    WeeklyReportInputsDTO,
)
from training.services.errors import InvalidInputError, ServiceError

log = logging.getLogger(__name__)

DAYS = 7
TOP_FINDINGS = 3
FILE_GLOB = "????-W??.md"
FENCE = "---"


def _pmc_point(session: Session, day: dt.date) -> ReportPmcDTO | None:
    point = fitness.get_pmc(session, date_from=day, date_to=day).latest
    if point is None:
        return None
    return ReportPmcDTO(
        date=point.date, ctl=point.ctl, atl=point.atl, tsb=point.tsb, ramp_rate=point.ramp_rate
    )


def reviewed_week(today: dt.date) -> tuple[dt.date, dt.date]:
    """Mon..Sun of the week the report reviews (the week of `today − 1`, as `llm.week_label`), ≤ today."""
    monday = today - dt.timedelta(days=1)
    monday -= dt.timedelta(days=monday.weekday())
    return monday, min(monday + dt.timedelta(days=DAYS - 1), today)


def weekly_inputs(session: Session, today: dt.date) -> WeeklyReportInputsDTO:
    """The prompt inputs from existing services, all anchored on the reviewed week (review phase 7): its
    activities and readiness, PMC at its end vs a week earlier, top-3 findings, its plan and the next
    week's plan, and the goal."""
    first, last = reviewed_week(today)
    listed = activities.list_activities(session, date_from=first, date_to=last, page_size=200)
    acts = [
        ReportActivityDTO(date=a.local_date, sport=a.sport, duration_s=a.duration_s, load=a.load_primary)
        for a in sorted(listed.items, key=lambda a: a.start_utc)
    ]
    days = [first + dt.timedelta(days=i) for i in range((last - first).days + 1)]
    readiness = []
    for day in days:
        r = sleep.get_readiness(session, day)
        readiness.append(ReportReadinessDTO(date=day, score=r.score, band=r.band))
    findings = sleep.get_correlations(session).findings[:TOP_FINDINGS]
    return WeeklyReportInputsDTO(
        today=today,
        activities=acts,
        pmc_now=_pmc_point(session, last),
        pmc_week_ago=_pmc_point(session, last - dt.timedelta(days=DAYS)),
        readiness=readiness,
        findings=findings,
        this_week=plan.get_week(session, first, today=today),
        next_week=plan.get_week(session, first + dt.timedelta(days=DAYS), today=today),
        goal=plan.get_goal(session, today),
    )


def _render(report: ReportDTO) -> str:
    stamp = report.generated_at.isoformat()
    head = [FENCE, f"week: {report.week}", f"generated_at: {stamp}", f"model: {report.model}", FENCE, ""]
    return "\n".join(head) + f"{report.markdown.strip()}\n"


def _parse(path: Path) -> ReportDTO | None:
    """The report stored in `path`; None when the header is missing or malformed."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):  # a broken file must not break the Dashboard
        return None
    if not lines or lines[0] != FENCE or FENCE not in lines[1:]:
        return None
    end = lines.index(FENCE, 1)
    meta = dict(line.split(": ", 1) for line in lines[1:end] if ": " in line)
    try:
        generated = dt.datetime.fromisoformat(meta["generated_at"])
        week, model = meta["week"], meta["model"]
    except (KeyError, ValueError):
        return None
    body = "\n".join(lines[end + 1 :]).strip()
    return ReportDTO(week=week, generated_at=generated, model=model, markdown=body)


def create_weekly_report(
    session: Session,
    today: dt.date,
    settings: Settings,
    *,
    client_factory: Callable[[str], Any] | None = None,
) -> ReportDTO:
    """Generate the report and store it as `<week>.md` (`llm.week_label`: the week that just ended when run
    on Sunday evening or Monday morning); an existing file of that week is replaced."""
    key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else ""
    if not key:
        raise InvalidInputError("the weekly report needs TRAINING_ANTHROPIC_API_KEY")
    inputs = weekly_inputs(session, today)
    try:
        generated = llm.generate_weekly_report(
            inputs, api_key=key, model=settings.ai_model, client_factory=client_factory
        )
    except llm.ReportError as exc:
        raise ServiceError(f"weekly report failed: {exc}") from None
    report = ReportDTO(
        week=llm.week_label(today),
        generated_at=dt.datetime.now(dt.UTC),
        model=generated.model,
        markdown=generated.text,
    )
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    (settings.reports_dir / f"{report.week}.md").write_text(_render(report), encoding="utf-8")
    return report


def latest_report(settings: Settings) -> ReportDTO | None:
    """The newest stored report (highest week label), or None."""
    directory = settings.reports_dir
    if not directory.is_dir():
        return None
    for path in sorted(directory.glob(FILE_GLOB), reverse=True):
        report = _parse(path)
        if report is not None:
            return report
    return None
