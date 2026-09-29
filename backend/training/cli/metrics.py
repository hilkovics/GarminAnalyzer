"""`training recompute` / `threshold` / `athlete` / `diagnostics`."""

import datetime as dt

import typer
from rich.markup import escape
from rich.table import Table
from sqlmodel import Session

from training import pipeline
from training.cli._app import app, console
from training.config import get_settings
from training.db.session import get_engine
from training.services.diagnostics import get_diagnostics


def _db_session() -> Session:
    return Session(get_engine(get_settings()))


def parse_pace(text: str) -> float:
    """ "m:ss" per km → m/s (presentation-layer conversion)."""
    minutes, sep, seconds = text.strip().partition(":")
    valid_seconds = seconds.isdigit() and len(seconds) == 2 and int(seconds) < 60
    if not sep or not minutes.isdigit() or not valid_seconds:
        raise typer.BadParameter("pace must be m:ss per km, e.g. 4:05")
    total = int(minutes) * 60 + int(seconds)
    if total <= 0:
        raise typer.BadParameter("pace must be m:ss per km, e.g. 4:05")
    return 1000.0 / total


def format_pace(speed: float | None) -> str:
    if not speed:
        return "–"
    total = round(1000.0 / speed)
    return f"{total // 60}:{total % 60:02d}/km"


@app.command()
def recompute(
    since: dt.datetime | None = typer.Option(
        None, "--since", formats=["%Y-%m-%d"], help="Only activities from this date."
    ),
    metrics_only: bool = typer.Option(False, "--metrics-only", help="Skip re-normalizing raw JSON."),
) -> None:
    """Recompute everything from stored raw JSON: typed tables → metrics → PMC. No network."""
    with _db_session() as session:
        result = pipeline.recompute(
            session, since=since.date() if since else None, renormalize=not metrics_only
        )
    console.print(
        f"Re-normalized {result.rebuilt_activities} activities · metrics for {result.metrics_computed} · "
        f"PMC {result.daily_load_days} days"
    )
    for line in result.errors[:10]:
        console.print(f"  [yellow]- {escape(line)}[/]")


threshold_app = typer.Typer(help="Time-versioned LTHR / threshold pace (METRICS §1).", no_args_is_help=True)
app.add_typer(threshold_app, name="threshold")


@threshold_app.command("add")
def threshold_add(
    sport: str = typer.Option(..., "--sport", help="run | bike"),
    lthr: float = typer.Option(..., "--lthr", help="Lactate-threshold HR (bpm)."),
    pace: str | None = typer.Option(None, "--pace", help="Run threshold pace m:ss per km (e.g. 4:05)."),
    valid_from: dt.datetime = typer.Option(..., "--valid-from", formats=["%Y-%m-%d"]),
) -> None:
    """Add (or replace) a threshold valid from a date; recomputes only the affected activities."""
    if sport not in ("run", "bike"):
        raise typer.BadParameter("sport must be run or bike")
    if pace and sport != "run":
        raise typer.BadParameter("--pace is only used for run thresholds")
    speed = parse_pace(pace) if pace else None
    with _db_session() as session:
        result = pipeline.set_threshold(
            session,
            sport=sport,
            valid_from=valid_from.date(),
            lthr=lthr,
            threshold_speed=speed,
            end=dt.date.today(),
        )
    console.print(
        f"Threshold {sport} from {valid_from:%Y-%m-%d}: LTHR {lthr:.0f}, pace {format_pace(speed)} · "
        f"recomputed {result.metrics_computed} activities"
    )


@threshold_app.command("list")
def threshold_list() -> None:
    """Show the threshold history."""
    from sqlalchemy import select

    from training.db.models import Threshold

    with _db_session() as session:
        rows = session.exec(select(Threshold).order_by(Threshold.sport, Threshold.valid_from)).scalars().all()
        table = Table("sport", "valid from", "LTHR", "threshold pace", "source")
        for t in rows:
            table.add_row(
                t.sport, f"{t.valid_from}", f"{t.lthr or '–'}", format_pace(t.threshold_speed), t.source
            )
    console.print(table)


@app.command()
def athlete(
    sex: str | None = typer.Option(None, "--sex", help="male | female (TRIMP constants, §2.2)"),
    max_hr: float | None = typer.Option(None, "--max-hr"),
    rest_hr: float | None = typer.Option(
        None, "--rest-hr", help="Override; default = 28-day median Garmin RHR."
    ),
    birth_year: int | None = typer.Option(None, "--birth-year"),
    weight_kg: float | None = typer.Option(None, "--weight-kg"),
) -> None:
    """Show or update athlete settings; any change recomputes all metrics."""
    if sex is not None and sex not in ("male", "female"):
        raise typer.BadParameter("sex must be male or female")
    fields = {
        "sex": sex,
        "max_hr": max_hr,
        "rest_hr_override": rest_hr,
        "birth_year": birth_year,
        "weight_kg": weight_kg,
    }
    with _db_session() as session:
        if all(v is None for v in fields.values()):
            current = pipeline.get_athlete(session)
            if current is None:
                console.print("No athlete settings yet – e.g. `training athlete --sex male --max-hr 190`.")
                return
        a = pipeline.set_athlete(session, **fields)
        console.print(
            f"sex {a.sex or '–'} · max HR {a.max_hr or '–'} · rest HR override {a.rest_hr_override or '–'} · "
            f"birth year {a.birth_year or '–'} · weight {a.weight_kg or '–'} kg"
        )
        if any(v is not None for v in fields.values()):
            result = pipeline.recompute(session, renormalize=False, end=dt.date.today())
            console.print(f"Recomputed {result.metrics_computed} activities")


@app.command()
def diagnostics() -> None:
    """Sync state, load sanity check vs Garmin training load (§2.5) and hrTSS/rTSS divergences."""
    with _db_session() as session:
        d = get_diagnostics(session)
    console.print(
        f"last activity sync: {d.last_activity_sync or '–'} · last wellness: {d.last_wellness_date or '–'}"
    )
    console.print(
        f"activities: {d.activities} (with metrics {d.activities_with_metrics}, without threshold "
        f"{d.activities_without_threshold}, without load {d.activities_without_load})"
    )
    if d.low_confidence_share is not None:
        console.print(f"low-confidence share: {d.low_confidence_share:.0%}")
    colour = {"good": "green", "fair": "yellow", "warning": "red"}.get(d.load_sanity.status, "white")
    r = f"{d.load_sanity.r:.2f}" if d.load_sanity.r is not None else "–"
    console.print(
        f"load vs Garmin training load: r = {r} (n = {d.load_sanity.n}) [{colour}]{d.load_sanity.status}[/]"
    )
    if d.load_sanity.status == "warning":
        console.print("  [red]r < 0.7 – review your LTHR / threshold pace (METRICS §2.5).[/]")
    if d.hrtss_rtss_divergent:
        console.print(f"hrTSS vs rTSS differ by > 40 % on {len(d.hrtss_rtss_divergent)} activities:")
        for x in d.hrtss_rtss_divergent[:15]:
            console.print(
                f"  {x.local_date} {x.garmin_id}: hrTSS {x.hrtss:.0f} vs rTSS {x.rtss:.0f} "
                f"({x.diff_pct:.0f} %)"
            )
        if len(d.hrtss_rtss_divergent) > 15:
            console.print(f"  … {len(d.hrtss_rtss_divergent) - 15} more")
        console.print("  garmin ids: " + ", ".join(str(x.garmin_id) for x in d.hrtss_rtss_divergent))
    if d.pending_activities or d.failed_activities:
        console.print(f"pending activities: {d.pending_activities} · failed: {len(d.failed_activities)}")
