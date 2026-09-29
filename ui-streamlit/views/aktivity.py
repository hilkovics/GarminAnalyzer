"""Aktivity: filterable, paged table; selecting a row (or `?activity=<id>`) shows the detail below."""

import math

import _db
import pandas as pd
import streamlit as st
from components.format import fmt_date, fmt_duration, fmt_km, fmt_load, fmt_speed, sport_label
from sections.activity_detail import render_activity_detail

from training.services import activities
from training.services.errors import ServiceError

PAGE_SIZE = 25
SPORT_FILTER = {"Všetky": None, "Beh": "run", "Bicykel": "bike", "Iné": "other"}
PAGE_KEY = "aktivity_page"


def _reset_page() -> None:
    st.session_state[PAGE_KEY] = 1


def _go_to(page: int) -> None:
    st.session_state[PAGE_KEY] = page


def _query_activity_id() -> int | None:
    raw = st.query_params.get("activity")
    return int(raw) if raw and raw.isdigit() else None


st.title("Aktivity")
st.session_state.setdefault(PAGE_KEY, 1)

c_from, c_to, c_sport = st.columns(3)
date_from = c_from.date_input(
    "Od", value=None, format="DD.MM.YYYY", key="aktivity_from", on_change=_reset_page
)
date_to = c_to.date_input("Do", value=None, format="DD.MM.YYYY", key="aktivity_to", on_change=_reset_page)
sport_choice = c_sport.selectbox("Šport", list(SPORT_FILTER), key="aktivity_sport", on_change=_reset_page)

if date_from and date_to and date_from > date_to:
    st.error("Dátum „Od“ je neskôr ako „Do“.")
    st.stop()

page = st.session_state[PAGE_KEY]
try:
    with _db.session() as session:
        listing = activities.list_activities(
            session,
            date_from=date_from,
            date_to=date_to,
            sport=SPORT_FILTER[sport_choice],
            page=page,
            page_size=PAGE_SIZE,
        )
except ServiceError as exc:
    st.error(str(exc))
    st.stop()

if not listing.items:
    if listing.total > 0 and page > 1:  # the data shrank under us: back to the first page
        _reset_page()
        st.rerun()
    st.info("Žiadne aktivity pre zvolený filter.")
    st.stop()

rows = [
    {
        "Dátum": fmt_date(a.local_date),
        "Šport": sport_label(a.sport),
        "Názov": a.name or "–",
        "Trvanie": fmt_duration(a.duration_s),
        "Vzdialenosť": fmt_km(a.distance_m, 2),
        "Tempo / rýchlosť": fmt_speed(a.avg_speed, a.sport),
        "Záťaž": fmt_load(a.load_primary, a.load_method, low_confidence=a.low_confidence),
    }
    for a in listing.items
]
event = st.dataframe(
    pd.DataFrame(rows),
    hide_index=True,
    width="stretch",
    on_select="rerun",
    selection_mode="single-row",
)
st.caption("⚠ = neznáma alebo nízko spoľahlivá záťaž. Klikni na riadok pre detail aktivity.")

# --- paging ---------------------------------------------------------------------------------------
last_page = max(1, math.ceil(listing.total / listing.page_size))
c_prev, c_info, c_next = st.columns([1, 3, 1])
c_prev.button(
    "‹ Novšie", disabled=listing.page <= 1, on_click=_go_to, args=(listing.page - 1,), width="stretch"
)
c_info.markdown(f"Strana **{listing.page}** z **{last_page}** · {listing.total} aktivít")
c_next.button(
    "Staršie ›",
    disabled=listing.page >= last_page,
    on_click=_go_to,
    args=(listing.page + 1,),
    width="stretch",
)

# --- detail ---------------------------------------------------------------------------------------
selected = event.selection.rows
activity_id = (
    listing.items[selected[0]].id if selected and selected[0] < len(listing.items) else _query_activity_id()
)
if activity_id is not None:
    st.divider()
    render_activity_detail(activity_id)
