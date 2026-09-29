"""Dashboard: this week vs the mean of the last 4 weeks, mini PMC, ACWR badge, sync health."""

import _db
import pandas as pd
import streamlit as st
from components.badges import acwr_badge
from components.format import (
    fmt_date,
    fmt_duration,
    fmt_km,
    fmt_load,
    fmt_num,
    fmt_signed,
    sport_label,
)
from components.pmc import pmc_chart
from components.weekly import WEEKLY_METRICS, week_compare_bars

from training.services import fitness
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

# --- today's form ---------------------------------------------------------------------------------
latest = dash.latest
if latest is None:
    st.info("Zatiaľ žiadne metriky. Spusti sync v Nastaveniach.")
else:
    c_ctl, c_atl, c_tsb, c_acwr, c_ramp = st.columns(5)
    c_ctl.metric("CTL (kondícia)", fmt_num(latest.ctl, 1), help="Chronická záťaž, 42-dňový priemer.")
    c_atl.metric("ATL (únava)", fmt_num(latest.atl, 1), help="Akútna záťaž, 7-dňový priemer.")
    c_tsb.metric("TSB (sviežosť)", fmt_signed(latest.tsb), help="CTL − ATL z predošlého dňa.")
    c_acwr.metric("ACWR", fmt_num(latest.acwr, 2), help="Pomer akútnej a chronickej záťaže.")
    c_acwr.markdown(acwr_badge(latest.acwr_band).markdown)
    c_ramp.metric("Nárast CTL / týždeň", fmt_signed(latest.ramp_rate))
    if latest.ramp_warning:
        c_ramp.markdown(":red-badge[príliš rýchly nárast]")
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
