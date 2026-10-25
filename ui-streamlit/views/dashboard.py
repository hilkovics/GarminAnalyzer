"""Dashboard: readiness, today's workout, form tiles, week vs last 4, mini PMC, sync health, report."""

import _db
import pandas as pd
import streamlit as st
from components.badges import acwr_badge
from components.format import (
    fmt_date,
    fmt_datetime,
    fmt_duration,
    fmt_km,
    fmt_load,
    fmt_num,
    fmt_signed,
    sport_label,
)
from components.pmc import pmc_chart
from components.weekly import WEEKLY_METRICS, week_compare_bars
from sections import dashboard_today

from training.config import get_settings
from training.services import fitness, plan as plan_service, report, sleep as sleep_service
from training.services.errors import ServiceError

st.title("Dashboard")

try:
    with _db.session() as session:
        dash = fitness.get_dashboard(session, today=_db.today())
except ServiceError as exc:
    st.error(str(exc))
    st.stop()

# --- sync health ----------------------------------------------------------------------------------
if dash.last_sync is None:
    st.error("Posledný sync: žiadny. Spusti ho v Nastaveniach alebo príkazom `uv run training sync`.")
elif dash.sync_stale:
    st.error(
        f"Posledný sync je starší ako 36 hodín (posledný: {fmt_date(dash.last_sync)}). "
        "Spusti ho v Nastaveniach alebo príkazom `uv run training sync`."
    )
else:
    st.caption(f"Posledný sync: {fmt_date(dash.last_sync)}")

# --- morning run health (PLAN phase 8); times are shown in the system local zone ----------------------
if dash.last_run_ok is None:
    st.caption("Automatický ranný beh zatiaľ nebežal – návod v docs/OPERATIONS.md.")
elif not dash.last_run_ok:
    st.error("Posledný ranný beh zlyhal – pozri Nastavenia → Sync a diagnostika")
elif dash.morning_run_stale:
    st.error(
        "Posledný úspešný ranný beh je starší ako 36 hodín "
        f"(posledný: {fmt_datetime(dash.last_successful_run, ', ')}). "
        "Pozri Nastavenia → Sync a diagnostika."
    )
else:
    st.caption(f"Posledný úspešný ranný beh: {fmt_datetime(dash.last_successful_run, ', ')}")

# --- readiness and today's workout ----------------------------------------------------------------
# get_today decides (and stores) today's plan when it does not exist yet, exactly as the Plán page does.
readiness, readiness_note, decision, decision_note = None, None, None, None
try:
    with _db.session() as session:
        readiness = sleep_service.get_readiness(session, _db.today())
except ServiceError as exc:
    readiness_note = str(exc)
try:
    with _db.session() as session:
        decision = plan_service.get_today(session, _db.today())
except ServiceError as exc:
    decision_note = str(exc)
c_ready, c_today = st.columns([1, 2.4])
with c_ready:
    dashboard_today.readiness_card(readiness, readiness_note)
with c_today:
    dashboard_today.today_card(decision, decision_note)

# --- today's form ---------------------------------------------------------------------------------
latest = dash.latest
if latest is None:
    st.info("Zatiaľ žiadne metriky. Spusti sync v Nastaveniach.")
else:
    c_ctl, c_atl, c_tsb, c_acwr, c_ramp = st.columns(5)
    with c_ctl, st.container(border=True, key="tile_ctl"):
        st.metric("CTL (kondícia)", fmt_num(latest.ctl, 1), help="Chronická záťaž, 42-dňový priemer.")
    with c_atl, st.container(border=True, key="tile_atl"):
        st.metric("ATL (únava)", fmt_num(latest.atl, 1), help="Akútna záťaž, 7-dňový priemer.")
    with c_tsb, st.container(border=True, key="tile_tsb"):
        st.metric("TSB (sviežosť)", fmt_signed(latest.tsb), help="CTL − ATL z predošlého dňa.")
    with c_acwr, st.container(border=True, key="tile_acwr"):
        st.metric("ACWR", fmt_num(latest.acwr, 2), help="Pomer akútnej a chronickej záťaže.")
        st.markdown(acwr_badge(latest.acwr_band).markdown)
    with c_ramp, st.container(border=True, key="tile_ramp"):
        st.metric("Nárast CTL / týždeň", fmt_signed(latest.ramp_rate))
        if latest.ramp_warning:
            st.markdown(":red-badge[príliš rýchly nárast]")
    if latest.warming_up:
        st.caption("Séria je ešte v prvých 90 dňoch – CTL a ATL sa zahrievajú a nie sú spoľahlivé.")

# --- this week vs last 4 --------------------------------------------------------------------------
st.subheader("Tento týždeň vs. priemer 4 predchádzajúcich")
st.caption(f"Týždeň od {fmt_date(dash.week_start)}")
averages = {w.sport: w for w in dash.last4_avg}
rows = []
for week in dash.this_week:
    avg = averages.get(week.sport)
    rows.append(
        {
            "Šport": sport_label(week.sport),
            "Záťaž": fmt_load(week.load),
            "Záťaž Ø 4 t": fmt_load(avg.load) if avg else "–",
            "Čas": fmt_duration(week.duration_s),
            "Čas Ø 4 t": fmt_duration(avg.duration_s) if avg else "–",
            "Vzdialenosť": fmt_km(week.distance_m),
            "Vzdialenosť Ø 4 t": fmt_km(avg.distance_m) if avg else "–",
            "Aktivity": week.n_activities,
        }
    )
if rows:
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    metric = st.radio(
        "Metrika grafu",
        list(WEEKLY_METRICS),
        format_func=lambda k: WEEKLY_METRICS[k][0],
        horizontal=True,
        key="dashboard_metric",
    )
    st.plotly_chart(week_compare_bars(dash.this_week, dash.last4_avg, metric), width="stretch")
else:
    st.info("Tento týždeň zatiaľ žiadna aktivita.")

# --- mini PMC -------------------------------------------------------------------------------------
st.subheader("Kondícia a únava (posledných 42 dní)")
st.plotly_chart(pmc_chart(dash.pmc, compact=True), width="stretch")

# --- weekly AI report (read from disk; the page never calls the API) ------------------------------
with st.expander("Týždenný report"):
    latest_report = report.latest_report(get_settings())
    if latest_report is None:
        st.info(
            "Týždenný report zatiaľ nie je. Zapni ho nastavením `TRAINING_ANTHROPIC_API_KEY` "
            "a spusti `uv run training weekly-report`."
        )
    else:
        st.caption(
            f"Týždeň {latest_report.week}, vygenerované {fmt_date(latest_report.generated_at.date())} "
            f"({latest_report.model})"
        )
        st.markdown(latest_report.markdown)
