"""Dashboard top row: readiness gauge and the "Dnešný tréning" card.

Rendering only. The workout, its steps, the estimate and the Garmin status come from `DailyDecisionDTO`; the
score and band from `ReadinessDTO`. The card is the compact version of the Plán page's today card.
"""

import streamlit as st
from components.badges import readiness_badge
from components.cards import meta_html, title_html
from components.format import fmt_duration, fmt_num, sport_label
from components.plan import status_badge, step_lines
from components.profile import workout_profile
from components.sleep import readiness_gauge
from streamlit.errors import StreamlitAPIException

from training.services.dto import DailyDecisionDTO, ReadinessDTO


def readiness_card(readiness: ReadinessDTO | None, unavailable: str | None = None) -> None:
    """ "Pripravenosť 0–100": the gauge, the band badge and the advice of the readiness service."""
    with st.container(border=True, key="dash_readiness"):
        st.caption("PRIPRAVENOSŤ · 0–100")
        if readiness is None:
            st.info(unavailable or "Pripravenosť dnes nie je k dispozícii.")
            return
        st.plotly_chart(readiness_gauge(readiness), width="stretch", key="dash_gauge")
        if readiness.available:
            st.markdown(f"{readiness_badge(readiness.band).markdown} **{readiness.message}**")
        else:
            st.caption(readiness.message)


def _open_plan_link() -> None:
    try:
        st.page_link("views/plan.py", label="Otvoriť plán", icon=":material/arrow_forward:")
    except StreamlitAPIException:  # page script run on its own (tests) – no registered "Plán" page
        st.caption("Plán nájdeš na stránke Plán.")


def today_card(decision: DailyDecisionDTO | None, unavailable: str | None = None) -> None:
    """Workout name, Garmin status, sport, duration, estimated load, profile and steps, link to Plán."""
    with st.container(border=True, key="dash_today"):
        if decision is None:
            st.caption("DNEŠNÝ TRÉNING")
            st.info(unavailable or "Dnešný tréning nie je k dispozícii.")
            _open_plan_link()
            return
        workout = decision.workout
        head, status = st.columns([3, 2], vertical_alignment="center")
        head.caption("DNEŠNÝ TRÉNING")
        status.markdown(status_badge(workout, None).markdown)
        st.markdown(title_html(workout.name), unsafe_allow_html=True)
        if workout.sport == "rest":
            st.write("Dnes voľno – oddych je súčasť tréningu.")
        else:
            c_sport, c_time, c_load = st.columns(3)
            c_sport.markdown(meta_html("Šport", sport_label(workout.sport)), unsafe_allow_html=True)
            c_time.markdown(meta_html("Trvanie", fmt_duration(workout.duration_s)), unsafe_allow_html=True)
            c_load.markdown(
                meta_html("Odhad záťaže (TSS-ekv.)", fmt_num(workout.estimated_load)), unsafe_allow_html=True
            )
            st.plotly_chart(workout_profile(workout.steps, height=150), width="stretch", key="dash_profile")
            st.caption("  ·  ".join(step_lines(workout.steps)))
        _open_plan_link()
