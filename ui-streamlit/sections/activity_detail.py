"""Activity detail block: summary, streams chart, laps, time in zones, load breakdown, subjective form.

Calls `training.services.activities` and renders the DTOs; no computation.
"""

import _db
import pandas as pd
import streamlit as st
from components.activity import activity_chart
from components.format import (
    fmt_date,
    fmt_duration_hms,
    fmt_km,
    fmt_load,
    fmt_num,
    fmt_pace,
    fmt_pct,
    fmt_speed,
    sport_label,
)
from components.zones import zones_bar

from training.services import activities
from training.services.dto import ActivityDetailDTO, SubjectiveIn
from training.services.errors import NotFoundError, ServiceError

STREAM_FIELDS = {"run": ["hr", "speed", "gap_speed", "alt"], "bike": ["hr", "speed", "alt"]}
STREAM_POINTS = 1500

FEEL_LABELS = {1: "1 – veľmi zle", 2: "2 – zle", 3: "3 – normálne", 4: "4 – dobre", 5: "5 – výborne"}
SORENESS_LABELS = {0: "0 – žiadna", 1: "1 – mierna", 2: "2 – stredná", 3: "3 – silná"}


def render_activity_detail(activity_id: int) -> None:
    """Load one activity by its internal id and render every section; errors become messages."""
    try:
        with _db.session() as session:
            detail = activities.get_activity(session, activity_id)
    except NotFoundError:
        st.error(f"Aktivita {activity_id} neexistuje.")
        return
    except ServiceError as exc:
        st.error(str(exc))
        return

    _summary(detail)
    _streams(detail)
    _laps(detail)
    _zones(detail)
    _load_breakdown(detail)
    _subjective_form(detail)


def _summary(detail: ActivityDetailDTO) -> None:
    s = detail.summary
    st.subheader(f"{s.name or 'Aktivita'} · {fmt_date(s.local_date)}")
    tags = [sport_label(s.sport)]
    if s.sub_sport:
        tags.append(s.sub_sport)
    if s.is_race:
        tags.append("preteky")
    if s.is_indoor:
        tags.append("indoor")
    st.caption(" · ".join(tags))
    cols = st.columns(6)
    cols[0].metric("Trvanie", fmt_duration_hms(s.duration_s))
    cols[1].metric("Vzdialenosť", fmt_km(s.distance_m, 2))
    cols[2].metric("Tempo" if s.sport != "bike" else "Rýchlosť", fmt_speed(s.avg_speed, s.sport))
    cols[3].metric("Priem. tep", fmt_num(s.avg_hr, 0, "bpm"))
    cols[4].metric("Max. tep", fmt_num(s.max_hr, 0, "bpm"))
    cols[5].metric("Prevýšenie", fmt_num(s.elev_gain_m, 0, "m"))
    if s.low_confidence:
        st.warning(
            f"Nízka spoľahlivosť záťaže (pokrytie tepu {fmt_pct(s.hr_coverage)}). Hodnoty ber s rezervou."
        )
    if s.load_primary is None:
        st.warning("Záťaž tejto aktivity je neznáma (chýba tep alebo prah).")


def _streams(detail: ActivityDetailDTO) -> None:
    s = detail.summary
    st.markdown("#### Priebeh")
    try:
        with _db.session() as session:
            streams = activities.get_streams(
                session,
                s.id,
                fields=STREAM_FIELDS["bike" if s.sport == "bike" else "run"],
                points=STREAM_POINTS,
            )
    except ServiceError as exc:
        st.info(f"Priebeh nie je k dispozícii: {exc}")
        return
    st.plotly_chart(activity_chart(streams, sport=s.sport), width="stretch")
    st.caption(f"{streams.points} bodov zo {streams.source_points} vzoriek.")


def _laps(detail: ActivityDetailDTO) -> None:
    st.markdown("#### Kolá")
    if not detail.laps:
        st.caption("Aktivita nemá žiadne kolá.")
        return
    sport = detail.summary.sport
    rows = [
        {
            "Kolo": lap.index,
            "Trvanie": fmt_duration_hms(lap.duration_s),
            "Vzdialenosť": fmt_km(lap.distance_m, 2),
            "Tempo" if sport != "bike" else "Rýchlosť": fmt_speed(lap.avg_speed, sport),
            "Priem. tep": fmt_num(lap.avg_hr, 0),
            "Max. tep": fmt_num(lap.max_hr, 0),
            "Prevýšenie (m)": fmt_num(lap.elev_gain_m, 0),
        }
        for lap in detail.laps
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _zones(detail: ActivityDetailDTO) -> None:
    st.markdown("#### Čas v zónach")
    th = detail.threshold
    if th is None:
        st.info("K dátumu aktivity nie je platný žiadny prah – zóny nie sú k dispozícii.")
        return
    pace = f", prahové tempo {fmt_pace(th.threshold_speed)}" if th.threshold_speed else ""
    st.caption(f"Prah platný od {fmt_date(th.valid_from)}: LTHR {fmt_num(th.lthr, 0, 'bpm')}{pace}.")
    if detail.pace_zones:
        c_hr, c_pace = st.columns(2)
        c_hr.markdown("**Tepové zóny**")
        c_hr.plotly_chart(zones_bar(detail.hr_zones, kind="hr"), width="stretch", key="zones_hr")
        c_pace.markdown("**Tempové zóny**")
        c_pace.plotly_chart(zones_bar(detail.pace_zones, kind="pace"), width="stretch", key="zones_pace")
    else:
        st.plotly_chart(zones_bar(detail.hr_zones, kind="hr"), width="stretch", key="zones_hr")


def _load_breakdown(detail: ActivityDetailDTO) -> None:
    s = detail.summary
    st.markdown("#### Záťaž")
    cols = st.columns(5)
    cols[0].metric("hrTSS", fmt_num(s.hrtss, 0))
    cols[1].metric("rTSS", fmt_num(s.rtss, 0))
    cols[2].metric("TRIMP (norm.)", fmt_num(s.trimp_norm, 0))
    cols[3].metric("IF (tep)", fmt_num(s.if_hr, 2))
    cols[4].metric("IF (tempo)", fmt_num(s.if_pace, 2))
    st.caption(
        f"Primárna záťaž: {fmt_load(s.load_primary, s.load_method, low_confidence=s.low_confidence)} · "
        f"Garmin training load: {fmt_num(s.garmin_training_load, 0)}"
    )


def _subjective_form(detail: ActivityDetailDTO) -> None:
    aid = detail.summary.id
    current = detail.subjective
    st.markdown("#### Subjektívne hodnotenie")
    with st.form(f"subjective_{aid}"):
        c_rpe, c_feel, c_sore = st.columns(3)
        rpe = c_rpe.selectbox(
            "RPE (1–10)",
            [None, *range(1, 11)],
            index=_index([None, *range(1, 11)], current.rpe if current else None),
            format_func=lambda v: "–" if v is None else str(v),
            key=f"rpe_{aid}",
        )
        feel = c_feel.selectbox(
            "Pocit (1–5)",
            [None, *FEEL_LABELS],
            index=_index([None, *FEEL_LABELS], current.feel if current else None),
            format_func=lambda v: "–" if v is None else FEEL_LABELS[v],
            key=f"feel_{aid}",
        )
        soreness = c_sore.selectbox(
            "Bolestivosť (0–3)",
            [None, *SORENESS_LABELS],
            index=_index([None, *SORENESS_LABELS], current.soreness if current else None),
            format_func=lambda v: "–" if v is None else SORENESS_LABELS[v],
            key=f"soreness_{aid}",
        )
        notes = st.text_area(
            "Poznámka",
            value=(current.notes or "") if current else "",
            max_chars=2000,
            key=f"notes_{aid}",
        )
        submitted = st.form_submit_button("Uložiť hodnotenie")
    if not submitted:
        return
    data = SubjectiveIn(rpe=rpe, feel=feel, soreness=soreness, notes=notes.strip() or None)
    try:
        with _db.session() as session:
            activities.save_subjective(session, aid, data)
    except ServiceError as exc:
        st.error(str(exc))
    else:
        st.success("Hodnotenie uložené.")


def _index(options: list, value: object) -> int:
    """Position of `value` in `options` (the None entry when unset or unknown)."""
    return options.index(value) if value in options else 0
