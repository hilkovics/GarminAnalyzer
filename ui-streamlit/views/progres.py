"""Progres: EF, decoupling, speed–HR curves, pace at reference HR, best efforts, predictions, proposals."""

import _db
import streamlit as st
from components.efforts import best_efforts_chart, curves_chart, hr_efforts_chart
from components.progress import decoupling_chart, ef_chart, pace_ref_chart
from sections import progress_tables

from training.services import progress
from training.services.errors import ServiceError

RANGES = {"90 dní": 90, "180 dní": 180, "1 rok": 365, "2 roky": 730}
SPORTS = {"run": "Beh", "bike": "Bicykel"}

st.title("Progres")

c_sport, c_range = st.columns([1, 2])
sport = c_sport.radio("Šport", list(SPORTS), format_func=SPORTS.get, horizontal=True, key="progress_sport")
days = RANGES[c_range.radio("Rozsah", list(RANGES), index=1, horizontal=True, key="progress_range")]

today = _db.today()
try:
    with _db.session() as session:
        ef = progress.get_ef_series(session, sport=sport, days=days, today=today, metric="ef")
        decoupling = progress.get_ef_series(
            session, sport=sport, days=days, today=today, metric="decoupling_pct"
        )
        pace_ref = progress.get_ef_series(
            session, sport="run", days=days, today=today, metric="pace_at_ref_hr_day"
        )
        curves = progress.get_speed_hr_curves(session, months=6, today=today)
        recent = progress.get_best_efforts(session, sport=sport, range="90d", today=today)
        all_time = progress.get_best_efforts(session, sport=sport, range="all", today=today)
        predictions = progress.get_predictions(session, today=today)
        proposals = progress.get_threshold_proposals(session, today=today)
except ServiceError as exc:
    st.error(str(exc))
    st.stop()

# --- EF -------------------------------------------------------------------------------------------
st.subheader("Efektivita (EF) – trend")
st.caption(
    "EF = priemerná rýchlosť (m/min) / priemerný tep. Iba steady-state aktivity; čiara je 28-dňový medián. "
    "Rastúca čiara = lepšia aeróbna kondícia."
)
if ef.caveat:
    st.warning("Bicykel: EF závisí od terénu a vetra – sleduj iba trend, nie jednotlivé jazdy.")
st.plotly_chart(ef_chart(ef), width="stretch")

st.subheader("Aeróbny decoupling")
st.caption("Pokles EF medzi 1. a 2. polovicou aktivity. Pod 5 % dobré, 5–10 % priemerné, nad 10 % slabé.")
st.plotly_chart(decoupling_chart(decoupling), width="stretch")

# --- run-only progress ------------------------------------------------------------------------------
if sport == "run":
    st.subheader("Krivka rýchlosť–tep (posledných 6 mesiacov)")
    st.caption(
        "Každá čiara = 28 dní končiace koncom mesiaca. Krivka posunutá nahor (rýchlejšie tempo pri "
        "rovnakom tepe) "
        "znamená zlepšenie."
    )
    st.plotly_chart(curves_chart(curves), width="stretch")

    st.subheader("Tempo pri referenčnom tepe (80 % LTHR)")
    st.plotly_chart(pace_ref_chart(pace_ref), width="stretch")
else:
    st.caption("Krivky rýchlosť–tep, tempo pri referenčnom tepe a predikcie pretekov sú len pre beh.")

# --- best efforts -----------------------------------------------------------------------------------
st.subheader("Najlepšie úseky: 90 dní vs celá história")
st.plotly_chart(best_efforts_chart(recent, all_time), width="stretch")
st.markdown("**Tep najlepších úsekov**")
st.plotly_chart(hr_efforts_chart(recent, all_time), width="stretch")

# --- predictions and proposals ----------------------------------------------------------------------
if sport == "run":
    st.subheader("Predikcie pretekov")
    progress_tables.predictions_table(predictions)

st.subheader("Návrhy prahov")
progress_tables.proposals_table(proposals)
progress_tables.proposals_link(proposals)
