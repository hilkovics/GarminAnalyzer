"""Nastavenia blocks: "Spustiť sync teraz" button and the diagnostics section.

The sync runs synchronously inside a spinner (no threads, CLAUDE.md); the result DTO or the service's
user-facing error message is rendered.
"""

import _db
import pandas as pd
import streamlit as st
from components.badges import load_sanity_badge
from components.format import fmt_date, fmt_num, fmt_pct, sport_label

from training.config import get_settings
from training.services import diagnostics as diagnostics_service
from training.services import sync
from training.services.dto import SyncResultDTO
from training.services.errors import ServiceError


def sync_now() -> None:
    """Button that runs `sync.run_sync` and shows its `SyncResultDTO` (or the `ServiceError` message)."""
    st.caption(
        "Stiahne nové aktivity a wellness dáta z Garmin Connect a prepočíta metriky. Môže trvať minúty."
    )
    if not st.button("Spustiť sync teraz", type="primary"):
        return
    try:
        with st.spinner("Synchronizujem s Garmin Connect…"), _db.session() as session:
            result = sync.run_sync(session, settings=get_settings(), today=_db.today())
    except ServiceError as exc:
        st.error(f"Sync zlyhal: {exc}")
        return
    _sync_result(result)


def _sync_result(result: SyncResultDTO) -> None:
    (st.warning if result.errors else st.success)(
        "Sync dokončený" + (" s chybami." if result.errors else ".")
    )
    cols = st.columns(4)
    cols[0].metric("Nové aktivity", result.activities_new)
    cols[1].metric("Aktualizované", result.activities_updated)
    cols[2].metric("Nezmenené", result.activities_unchanged)
    cols[3].metric("Wellness dni", result.wellness_days)
    cols = st.columns(4)
    cols[0].metric("Čakajúce", result.activities_pending)
    cols[1].metric("Zlyhané", result.activities_failed)
    cols[2].metric("Prepočítané metriky", result.metrics_computed)
    cols[3].metric("Dni PMC", result.pmc_days)
    for message in result.errors:
        st.warning(message)


def diagnostics() -> None:
    """Sync state, queues, data quality and the METRICS §2.5 load sanity check."""
    try:
        with _db.session() as session:
            d = diagnostics_service.get_diagnostics(session)
    except ServiceError as exc:
        st.error(str(exc))
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Posledný sync aktivít", fmt_date(d.last_activity_sync))
    c2.metric("Posledné wellness", fmt_date(d.last_wellness_date))
    c3.metric("Backfill (kurzor)", fmt_date(d.backfill_cursor))
    c4.metric("Čakajúce", f"{d.pending_activities} akt. / {d.pending_wellness_days} dní")
    if d.failed_activities:
        st.warning("Zlyhané aktivity (Garmin id): " + ", ".join(str(i) for i in d.failed_activities))
    if d.failed_wellness_days:
        st.warning("Zlyhané wellness dni: " + ", ".join(fmt_date(x) for x in d.failed_wellness_days))

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Aktivity", d.activities)
    c2.metric("S metrikami", d.activities_with_metrics)
    c3.metric("Bez prahu", d.activities_without_threshold)
    c4.metric("Bez záťaže", d.activities_without_load)
    c5.metric("Nízka spoľahlivosť", fmt_pct(d.low_confidence_share))

    sanity = d.load_sanity
    st.markdown("##### Kontrola záťaže vs. Garmin training load")
    c_r, c_note = st.columns([1, 3])
    c_r.metric(
        "Pearson r",
        fmt_num(sanity.r, 2),
        help="Korelácia load_primary s Garmin training load (METRICS §2.5).",
    )
    c_note.markdown(f"{load_sanity_badge(sanity.status).markdown} · n = {sanity.n} aktivít")
    c_note.caption("r > 0,8 je dobré; pod 0,7 najprv skontroluj LTHR.")

    st.markdown("##### Behy, kde sa hrTSS a rTSS líšia o viac ako 40 %")
    if not d.hrtss_rtss_divergent:
        st.caption("Žiadne.")
        return
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "Garmin id": x.garmin_id,
                    "Dátum": fmt_date(x.local_date),
                    "Šport": sport_label(x.sport),
                    "hrTSS": fmt_num(x.hrtss, 0),
                    "rTSS": fmt_num(x.rtss, 0),
                    "Rozdiel (%)": fmt_num(x.diff_pct, 0),
                }
                for x in d.hrtss_rtss_divergent
            ]
        ),
        hide_index=True,
        width="stretch",
    )
