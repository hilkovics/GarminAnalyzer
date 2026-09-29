"""Progres tables: race predictions and threshold proposals (+ the "apply from today" action for Nastavenia).

Rendering only. Pace and h:mm:ss are formatted here; every number comes from the DTOs. Applying a proposal
calls `training.services.progress.apply_proposal`, which recomputes the estimate itself.
"""

import _db
import pandas as pd
import streamlit as st
from components.format import (
    DASH,
    fmt_date,
    fmt_km,
    fmt_num,
    fmt_pace,
    fmt_signed,
    fmt_time_hms,
    sport_label,
)

from training.services import progress as progress_service
from training.services.dto import PredictionsDTO, ProposalDTO
from training.services.errors import ServiceError

FLASH_KEY = "settings_flash"  # shown by the Nastavenia page after a rerun
PREDICTION_NAMES = {"5k": "5 km", "10k": "10 km", "half": "Polmaratón", "marathon": "Maratón"}
FIELD_LABELS = {"threshold_speed": "Prahové tempo", "lthr": "LTHR"}


def predictions_table(dto: PredictionsDTO) -> None:
    """Reference performance, stale warning and the Riegel / Daniels table."""
    ref = dto.reference
    if ref is None:
        st.info(
            "Zatiaľ žiadny referenčný výkon (pretek alebo najlepší úsek ≥ 10 min so známou vzdialenosťou)."
        )
        return
    source = "pretek" if ref.source == "race" else "najlepší úsek"
    st.caption(
        f"Referencia: {fmt_km(ref.distance_m, 2)} za {fmt_time_hms(ref.time_s)} "
        f"({fmt_pace(ref.distance_m / ref.time_s)}), {fmt_date(ref.local_date)}, {source} · "
        f"VDOT {ref.vdot:.1f}"
    )
    if dto.stale:
        st.warning("⚠ Referenčný výkon je starší ako 60 dní – predikcie môžu byť zastarané.")
    rows = [
        {
            "Vzdialenosť": PREDICTION_NAMES.get(p.name, p.name),
            "Riegel": fmt_time_hms(p.riegel_s),
            "Daniels (VDOT)": fmt_time_hms(p.daniels_s),
            "Tempo (Daniels)": fmt_pace(p.distance_m / p.daniels_s),
            "Poznámka": "⚠ extrapolované (referencia < ¼ cieľa)" if p.extrapolated else "",
        }
        for p in dto.predictions
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def _value(p: ProposalDTO, x: float | None) -> str:
    if x is None:
        return DASH
    return fmt_pace(x) if p.field == "threshold_speed" else fmt_num(x, 0, "bpm")


def _change(p: ProposalDTO) -> str:
    if p.change is None:
        return DASH
    return f"{p.change * 100:+.1f} %" if p.field == "threshold_speed" else f"{fmt_signed(p.change, 0)} bpm"


def _garmin(p: ProposalDTO) -> str:
    parts = []
    if p.field == "lthr" and p.garmin_lthr is not None:
        parts.append(f"LT tep {p.garmin_lthr:.0f} bpm")
    if p.field == "threshold_speed" and p.garmin_lt_speed is not None:
        parts.append(f"LT tempo {fmt_pace(p.garmin_lt_speed)}")
    if p.garmin_vo2max is not None:
        parts.append(f"VO2max {p.garmin_vo2max:.0f}")
    return " · ".join(parts) or DASH


def proposals_table(proposals: list[ProposalDTO]) -> None:
    """All estimates with the current value, the change and whether the rule proposes it (never automatic)."""
    if not proposals:
        st.info("Zatiaľ žiadne návrhy prahov – chýbajú najlepšie úseky z posledných 90 dní.")
        return
    rows = [
        {
            "Šport": sport_label(p.sport),
            "Prah": FIELD_LABELS.get(p.field, p.field),
            "Aktuálne": _value(p, p.current),
            "Odhad": _value(p, p.estimate),
            "Zmena": _change(p),
            "Navrhnúť": "áno" if p.propose else "nie",
            "Garmin": _garmin(p),
            "Základ": p.basis,
        }
        for p in proposals
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def proposals_link(proposals: list[ProposalDTO]) -> None:
    """On Progres: a button leading to Nastavenia, where a proposal is applied."""
    if any(p.propose for p in proposals) and st.button("Použiť návrh v Nastaveniach", key="goto_settings"):
        st.switch_page("views/nastavenia.py")


def apply_actions(proposals: list[ProposalDTO]) -> None:
    """On Nastavenia: one button per proposed change, storing it as a threshold valid from today."""
    st.markdown("##### Návrhy prahov z posledných 90 dní")
    st.caption("Návrhy sa nikdy nepoužijú automaticky. Použitie uloží nový prah platný od dnes.")
    proposals_table(proposals)
    for p in (p for p in proposals if p.propose):
        what = f"{FIELD_LABELS.get(p.field, p.field)} {_value(p, p.estimate)}"
        label = f"Použiť: {sport_label(p.sport)} – {what} od dnes"
        if not st.button(label, key=f"apply_{p.sport}_{p.field}"):
            continue
        try:
            with st.spinner("Ukladám prah a prepočítavam metriky…"), _db.session() as session:
                progress_service.apply_proposal(session, sport=p.sport, field=p.field, today=_db.today())
        except ServiceError as exc:
            st.error(str(exc))
        else:
            st.session_state[FLASH_KEY] = (
                f"Návrh prahu ({sport_label(p.sport)}, {FIELD_LABELS[p.field]}) uložený od dnes."
            )
            st.rerun()
