"""Nastavenia: athlete, threshold history, zone preview, sync now, diagnostics."""

import _db
import streamlit as st
from sections import diagnostics, settings_forms

from training.services import settings as settings_service
from training.services.errors import ServiceError

st.title("Nastavenia")

flash = st.session_state.pop(settings_forms.FLASH_KEY, None)
if flash:
    st.success(flash)

try:
    with _db.session() as session:
        cfg = settings_service.get_settings(session, today=_db.today())
except ServiceError as exc:
    st.error(str(exc))
    st.stop()

tab_athlete, tab_thresholds, tab_sync = st.tabs(["Atlét", "Prahy a zóny", "Sync a diagnostika"])

with tab_athlete:
    settings_forms.athlete_form(cfg.athlete)

with tab_thresholds:
    st.markdown("##### História prahov")
    settings_forms.threshold_history(cfg)
    settings_forms.add_threshold_form()
    settings_forms.zone_preview(cfg)

with tab_sync:
    st.markdown("##### Sync")
    diagnostics.sync_now()
    st.markdown("##### Diagnostika")
    diagnostics.diagnostics()
