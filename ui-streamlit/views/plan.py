"""Plán: today's workout, this week (planned vs done), the season timeline, the goal and preferred days."""

import _db
import streamlit as st
from components.plan import season_chart
from sections import plan_blocks

from training.services import plan as plan_service, settings as settings_service
from training.services.errors import ServiceError

st.title("Plán")

flash = st.session_state.pop(plan_blocks.FLASH_KEY, None)
if flash:
    st.success(flash)

today = _db.today()
try:
    with _db.session() as session:
        decision = plan_service.get_today(session, today)
        week = plan_service.get_week(session, today, today=today)
        season = plan_service.get_season(session, today)
        goal = plan_service.get_goal(session, today)
        cfg = settings_service.get_settings(session, today=today)
except ServiceError as exc:
    st.error(str(exc))
    st.stop()

st.subheader("Dnešný tréning")
plan_blocks.today_card(decision)

st.subheader("Tento týždeň")
plan_blocks.week_block(week)

st.subheader("Sezóna")
plan_blocks.goal_summary(goal, season)
st.plotly_chart(season_chart(season), width="stretch", key="plan_season")

with st.expander("Cieľ", expanded=goal is None):
    plan_blocks.goal_editor(goal)
with st.expander("Preferované dni v týždni"):
    st.caption(
        "Rola dňa určuje typ tréningu; šport „Podľa trénera“ zvolí pravidlá (kvalita a dlhý = šport cieľa)."
    )
    plan_blocks.preferred_days_editor(cfg.athlete)
