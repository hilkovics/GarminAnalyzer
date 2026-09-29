"""Spánok: readiness today, sleep stages, sleep score and RHR with baselines, sleep debt, findings."""

import datetime as dt

import _db
import streamlit as st
from components.sleep import (
    readiness_gauge,
    rhr_chart,
    sleep_debt_chart,
    sleep_score_chart,
    sleep_stages_chart,
)
from sections import sleep_blocks

from training.services import sleep as sleep_service
from training.services.dto import CorrelationsDTO
from training.services.errors import ServiceError

RANGES = {"30 dní": 30, "90 dní": 90, "180 dní": 180}
SPORTS = {"run": "Beh", "bike": "Bicykel"}
CORRELATIONS_TTL_S = 600


@st.cache_data(ttl=CORRELATIONS_TTL_S, show_spinner="Počítam korelácie…")
def load_correlations(sport: str) -> CorrelationsDTO:
    """The (slow) bootstrap runs in the service; this only keeps the DTO for ten minutes."""
    with _db.session() as session:
        return sleep_service.get_correlations(session, sport=sport)


st.title("Spánok")

today = _db.today()
days = RANGES[
    st.radio("Rozsah", list(RANGES), index=1, horizontal=True, key="sleep_range")  # type: ignore[arg-type]
]
try:
    with _db.session() as session:
        readiness = sleep_service.get_readiness(session, today)
        wellness = sleep_service.get_wellness(
            session, date_from=today - dt.timedelta(days=days - 1), date_to=today
        )
except ServiceError as exc:
    st.error(str(exc))
    st.stop()

# --- readiness --------------------------------------------------------------------------------------
st.subheader("Pripravenosť dnes")
c_gauge, c_table = st.columns([1, 2])
c_gauge.plotly_chart(readiness_gauge(readiness), width="stretch", key="sleep_gauge")
with c_table:
    sleep_blocks.readiness_block(readiness)

# --- sleep ------------------------------------------------------------------------------------------
st.subheader("Dĺžka a fázy spánku")
st.plotly_chart(sleep_stages_chart(wellness), width="stretch", key="sleep_stages")

st.subheader("Skóre spánku")
st.caption("Čiara = 28-dňový medián, pás = ± MAD (medián absolútnych odchýlok).")
st.plotly_chart(sleep_score_chart(wellness), width="stretch", key="sleep_score")

st.subheader("Pokojový tep")
st.plotly_chart(rhr_chart(wellness), width="stretch", key="sleep_rhr")

st.subheader("Spánkový dlh (7 nocí)")
st.caption("Súčet rozdielov oproti max(8 h, medián 28 dní) za 7 nocí; záporná hodnota = prebytok spánku.")
st.plotly_chart(sleep_debt_chart(wellness), width="stretch", key="sleep_debt")

# --- findings ---------------------------------------------------------------------------------------
st.subheader("Zistenia")
sport = st.radio("Šport", list(SPORTS), format_func=SPORTS.get, horizontal=True, key="sleep_sport")  # type: ignore[arg-type]
try:
    correlations = load_correlations(sport)
except ServiceError as exc:
    st.error(str(exc))
else:
    sleep_blocks.findings_block(correlations)
