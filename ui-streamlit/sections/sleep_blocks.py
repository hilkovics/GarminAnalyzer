"""Spánok page blocks: the readiness breakdown and the "Zistenia" (findings) list.

Rendering only. Every number and sentence comes from the DTOs (`ReadinessDTO`, `CorrelationsDTO`); h:mm and
signs are formatted here.
"""

import pandas as pd
import streamlit as st
from components.badges import readiness_badge
from components.format import DASH, fmt_duration, fmt_num, fmt_pct, fmt_rho, fmt_signed

from training.services.dto import CorrelationDTO, CorrelationsDTO, ReadinessComponentDTO, ReadinessDTO

COMPONENT_LABELS = {
    "rhr": "Pokojový tep",
    "sleep": "Spánok",
    "body_battery": "Body Battery",
    "form": "Forma (TSB)",
}
TOP_FINDINGS = 10


def _value(c: ReadinessComponentDTO, x: float | None) -> str:
    if x is None:
        return DASH
    if c.unit == "bpm":
        return fmt_num(x, 0, "bpm")
    if c.unit == "s":
        return fmt_duration(x)
    if c.unit == "TSB":
        return fmt_signed(x)
    return fmt_num(x, 0)


def readiness_block(dto: ReadinessDTO) -> None:
    """Message with the band badge and the component table (score, renormalized weight, input, baseline)."""
    if not dto.available:
        st.info(dto.message)
    else:
        st.markdown(f"{readiness_badge(dto.band).markdown} **{dto.message}**")
    rows = [
        {
            "Zložka": COMPONENT_LABELS.get(c.name, c.name),
            "Skóre": fmt_num(c.score, 0),
            "Váha": fmt_pct(c.weight),
            "Hodnota": _value(c, c.value),
            "Baseline (medián 28 d)": _value(c, c.baseline),
        }
        for c in dto.components
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    if any(c.name == "sleep" and c.unit == "s" and c.value is not None for c in dto.components):
        st.caption("Skóre spánku chýba – použitý prepočet z dĺžky spánku.")


def _finding(f: CorrelationDTO) -> None:
    st.markdown(f"**{f.sentence}**")
    if f.partial_rho is not None:
        main = f"parciálne ρ = {fmt_rho(f.partial_rho, f.partial_ci_low, f.partial_ci_high)}"
        raw = f" · surové ρ = {fmt_rho(f.rho, f.ci_low, f.ci_high)}"
    else:
        main = f"ρ = {fmt_rho(f.rho, f.ci_low, f.ci_high)}"
        raw = ""
    st.caption(f"n = {f.n} · {main}{raw}")


def findings_block(dto: CorrelationsDTO) -> None:
    """The fixed caveat, findings sorted by |ρ| (top 10, the rest folded) and the pairs lacking data."""
    st.info(dto.caveat)
    days = ", ".join(f"{sport}: {n}" for sport, n in dto.n_days.items())
    st.caption(f"Dni s aktivitou (dataset): {days}")
    if not dto.findings:
        st.info(f"Zatiaľ žiadne zistenia – každá dvojica potrebuje aspoň {dto.min_n} dní s údajmi.")
    for f in dto.findings[:TOP_FINDINGS]:
        _finding(f)
    if len(dto.findings) > TOP_FINDINGS:
        with st.expander(f"Ďalšie zistenia ({len(dto.findings) - TOP_FINDINGS})"):
            for f in dto.findings[TOP_FINDINGS:]:
                _finding(f)
    if dto.insufficient:
        with st.expander(f"Nedostatok dát (n < {dto.min_n}): {len(dto.insufficient)} dvojíc"):
            for f in dto.insufficient:
                st.caption(f.sentence)
