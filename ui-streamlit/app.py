"""Streamlit entry point: page config and navigation.

Structure (no business logic anywhere – pages call `training.services` and render the DTOs):

- `app.py`        page config + `st.navigation`
- `views/`        one script per page (Dashboard, Aktivity, Fitness, Progres, Spánok, Plán, Nastavenia)
- `sections/`     reusable Streamlit render blocks for the bigger pages (activity detail, settings, …)
- `components/`   Plotly figure builders and formatters: DTO in, figure/string out, no Streamlit import
- `_db.py`        DB session helper (`st.cache_resource` engine) and "today"

Run with `uv run streamlit run ui-streamlit/app.py`. Plán is a placeholder until phase 6.
"""

import streamlit as st

st.set_page_config(page_title="Tréning", page_icon=":material/directions_run:", layout="wide")

PAGES = [
    st.Page(
        "views/dashboard.py", title="Dashboard", icon=":material/dashboard:", default=True
    ),  # served at /
    st.Page("views/aktivity.py", title="Aktivity", icon=":material/directions_run:", url_path="aktivity"),
    st.Page("views/fitness.py", title="Fitness", icon=":material/monitoring:", url_path="fitness"),
    st.Page("views/progres.py", title="Progres", icon=":material/trending_up:", url_path="progres"),
    st.Page("views/spanok.py", title="Spánok", icon=":material/bedtime:", url_path="spanok"),
    st.Page("views/plan.py", title="Plán", icon=":material/event_note:", url_path="plan"),
    st.Page("views/nastavenia.py", title="Nastavenia", icon=":material/settings:", url_path="nastavenia"),
]

st.navigation(PAGES).run()
