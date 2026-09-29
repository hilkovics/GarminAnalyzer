"""Fitness: PMC chart with the warming-up band, weekly bars and the load flags of the latest day."""

import datetime as dt

import _db
import streamlit as st
from components.badges import acwr_badge
from components.format import fmt_date, fmt_num, fmt_signed
from components.pmc import pmc_chart
from components.weekly import WEEKLY_METRICS, weekly_bars

from training.services import fitness
from training.services.errors import ServiceError

RANGES: dict[str, int | None] = {"90 dní": 90, "180 dní": 180, "1 rok": 365, "Všetko": None}

st.title("Fitness")

c_range, c_weeks, c_metric = st.columns([2, 2, 2])
range_label = c_range.radio("Rozsah PMC", list(RANGES), index=2, horizontal=True, key="fitness_range")
weeks = c_weeks.slider("Týždne v grafe", min_value=12, max_value=52, value=12, step=4, key="fitness_weeks")
metric = c_metric.radio(
    "Metrika týždňov",
    list(WEEKLY_METRICS),
    format_func=lambda k: WEEKLY_METRICS[k][0],
    horizontal=True,
    key="fitness_metric",
)

today = _db.today()
days = RANGES[range_label]
try:
    with _db.session() as session:
        pmc = fitness.get_pmc(session, date_from=today - dt.timedelta(days=days - 1) if days else None)
        weekly = fitness.get_weekly(session, weeks=weeks, today=today)
except ServiceError as exc:
    st.error(str(exc))
    st.stop()

# --- flags of the latest point --------------------------------------------------------------------
latest = pmc.latest
if latest is None:
    st.info("Zatiaľ žiadne metriky. Spusti sync v Nastaveniach.")
else:
    st.caption(f"Posledný bod série: {fmt_date(latest.date)}")
    c_acwr, c_mono, c_strain, c_ramp = st.columns(4)
    c_acwr.metric("ACWR", fmt_num(latest.acwr, 2), help="Pomer akútnej (7 d) a chronickej (28 d) záťaže.")
    c_acwr.markdown(acwr_badge(latest.acwr_band).markdown)
    c_mono.metric(
        "Monotónnosť", fmt_num(latest.monotony, 2), help="Priemer / smerodajná odchýlka záťaže za 7 dní."
    )
    c_strain.metric("Strain", fmt_num(latest.strain, 0), help="Súčet záťaže za 7 dní krát monotónnosť.")
    c_ramp.metric("Nárast CTL / týždeň", fmt_signed(latest.ramp_rate))
    if latest.ramp_warning:
        st.warning("CTL rastie rýchlejšie ako 6 bodov za týždeň – pozor na preťaženie.")
    if latest.warming_up:
        st.caption("Séria je ešte v prvých 90 dňoch – hodnoty sa zahrievajú a nie sú spoľahlivé.")

# --- PMC ------------------------------------------------------------------------------------------
st.subheader("Výkonnostný manažment (PMC)")
st.plotly_chart(pmc_chart(pmc), width="stretch")
if pmc.warming_up_until is not None:
    st.caption(f"Sivé pásmo = zahrievanie do {fmt_date(pmc.warming_up_until)} (prvých 90 dní série).")

# --- weekly bars ----------------------------------------------------------------------------------
st.subheader(f"{WEEKLY_METRICS[metric][0]} po týždňoch ({weeks} týždňov)")
st.plotly_chart(weekly_bars(weekly, metric), width="stretch")
