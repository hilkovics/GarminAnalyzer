"""`training propose-thresholds`: the METRICS §6.3 proposals, the same list the Progres page shows."""

import datetime as dt

from rich.markup import escape
from rich.table import Table

from training.cli._app import app, console
from training.cli.metrics import _db_session, format_pace
from training.services.dto import ProposalDTO
from training.services.progress import get_threshold_proposals


def _value(p: ProposalDTO, x: float | None) -> str:
    if x is None:
        return "–"
    return format_pace(x) if p.field == "threshold_speed" else f"{x:.0f} bpm"


def _fmt(x: float | None, digits: int) -> str:
    return "–" if x is None else f"{x:.{digits}f}"


def _change(p: ProposalDTO) -> str:
    if p.change is None:
        return "–"
    return f"{p.change:+.1%}" if p.field == "threshold_speed" else f"{p.change:+.0f} bpm"


def _today() -> dt.date:
    return dt.date.today()


@app.command("propose-thresholds")
def propose_thresholds() -> None:
    """Print LTHR / threshold-pace proposals from the last 90 days (never applied automatically)."""
    with _db_session() as session:
        proposals = get_threshold_proposals(session, today=_today())
    if not proposals:
        console.print(
            "No proposals yet: not enough best efforts in the last 90 days (run `training recompute`)."
        )
        return
    table = Table("sport", "field", "current", "estimate", "change", "propose", "basis", show_lines=False)
    for p in proposals:
        table.add_row(
            p.sport,
            "threshold pace" if p.field == "threshold_speed" else "LTHR",
            _value(p, p.current),
            _value(p, p.estimate),
            _change(p),
            "[green]yes[/]" if p.propose else "no",
            escape(p.basis),
        )
    console.print(table)
    garmin = next((p for p in proposals if p.sport == "run"), None)
    if garmin and any(
        v is not None for v in (garmin.garmin_lthr, garmin.garmin_lt_speed, garmin.garmin_vo2max)
    ):
        console.print(
            f"Garmin: lactate-threshold HR {_fmt(garmin.garmin_lthr, 0)} · "
            f"LT pace {format_pace(garmin.garmin_lt_speed)} · VO2max {_fmt(garmin.garmin_vo2max, 1)}"
        )
    console.print("Apply one with `training threshold add ...` or in the Nastavenia page.")
