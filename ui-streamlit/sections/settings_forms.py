"""Nastavenia blocks: athlete form, threshold history + "add threshold" form, zone preview.

Pages parse and format only. The pace typed as m:ss is converted to m/s here in the UI layer
(`components.format.parse_pace`); everything else is passed to `training.services.settings` untouched.
"""

import datetime as dt

import _db
import pandas as pd
import streamlit as st
from components.format import fmt_date, fmt_num, fmt_pace, fmt_zone_range, parse_pace, sport_label
from pydantic import ValidationError

from training.services import settings as settings_service
from training.services.dto import AthleteDTO, AthleteIn, SettingsDTO, ThresholdIn
from training.services.errors import ServiceError

FLASH_KEY = "settings_flash"
SEX_LABELS = {None: "–", "male": "muž", "female": "žena"}
THRESHOLD_SPORTS = ["run", "bike"]


def _saved(message: str) -> None:
    """Remember a success message across the rerun that refreshes the tables above the form."""
    st.session_state[FLASH_KEY] = message
    st.rerun()


def athlete_form(athlete: AthleteDTO | None) -> None:
    """Athlete profile (TRIMP inputs). Empty fields are not changed (`AthleteIn` semantics)."""
    st.caption("Prázdne polia sa nemenia. Pokojový tep bez ručnej hodnoty je 28-dňový medián z Garminu.")
    if athlete is not None:
        st.caption(f"Pokojový tep použitý dnes: {fmt_num(athlete.rest_hr_current, 0, 'bpm')}")
    sex_options = list(SEX_LABELS)
    with st.form("athlete_form"):
        c1, c2, c3 = st.columns(3)
        sex = c1.selectbox(
            "Pohlavie",
            sex_options,
            index=sex_options.index(athlete.sex) if athlete and athlete.sex in sex_options else 0,
            format_func=SEX_LABELS.get,
        )
        birth_year = c2.number_input(
            "Rok narodenia",
            min_value=1900,
            max_value=dt.date.today().year,
            value=athlete.birth_year if athlete else None,
            step=1,
        )
        weight = c3.number_input(
            "Hmotnosť (kg)", min_value=1.0, value=athlete.weight_kg if athlete else None, step=0.5
        )
        c4, c5, c6 = st.columns(3)
        max_hr = c4.number_input(
            "Maximálny tep (bpm)", min_value=1.0, value=athlete.max_hr if athlete else None, step=1.0
        )
        rest_hr = c5.number_input(
            "Pokojový tep – ručná hodnota (bpm)",
            min_value=1.0,
            value=athlete.rest_hr_override if athlete else None,
            step=1.0,
        )
        split = c6.number_input(
            "Podiel behu na týždennej záťaži (%)",
            min_value=0.0,
            max_value=100.0,
            value=athlete.run_bike_split * 100 if athlete and athlete.run_bike_split is not None else None,
            step=5.0,
        )
        clear_rest = st.checkbox(
            "Zmazať ručný pokojový tep (použiť 28-dňový medián z Garminu)",
            value=False,
            disabled=not (athlete and athlete.rest_hr_override is not None),
        )
        submitted = st.form_submit_button("Uložiť atléta")
    if not submitted:
        return
    try:
        data = AthleteIn(
            sex=sex,
            birth_year=int(birth_year) if birth_year is not None else None,
            max_hr=max_hr,
            rest_hr_override=None if clear_rest else rest_hr,
            clear_rest_hr_override=clear_rest,
            weight_kg=weight,
            run_bike_split=split / 100 if split is not None else None,
        )
        with _db.session() as session:
            settings_service.update_athlete(session, data, today=_db.today())
    except (ServiceError, ValidationError) as exc:
        st.error(str(exc))
    else:
        _saved("Údaje atléta uložené.")


def threshold_history(cfg: SettingsDTO) -> None:
    """Threshold table (full history, the record valid today is marked)."""
    if not cfg.thresholds:
        st.info("Zatiaľ nie je zadaný žiadny prah. Pridaj prvý nižšie.")
        return
    current_ids = {t.id for t in cfg.current.values() if t is not None}
    rows = [
        {
            "Šport": sport_label(t.sport),
            "Platný od": fmt_date(t.valid_from),
            "LTHR (bpm)": fmt_num(t.lthr, 0),
            "Prahové tempo": fmt_pace(t.threshold_speed),
            "Zdroj": t.source,
            "Platí dnes": "áno" if t.id in current_ids else "",
        }
        for t in cfg.thresholds
    ]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")


def add_threshold_form() -> None:
    """ "Pridať prah": sport, LTHR, pace as m:ss (run only), valid-from date."""
    st.markdown("##### Pridať prah")
    with st.form("threshold_form"):
        c1, c2, c3, c4 = st.columns(4)
        sport = c1.selectbox("Šport", THRESHOLD_SPORTS, format_func=sport_label)
        lthr = c2.number_input("LTHR (bpm)", min_value=1.0, value=None, step=1.0)
        pace_text = c3.text_input("Prahové tempo (m:ss, iba beh)", placeholder="4:10")
        valid_from = c4.date_input("Platný od", value=_db.today(), format="DD.MM.YYYY")
        submitted = st.form_submit_button("Pridať prah")
    if not submitted:
        return
    if lthr is None:
        st.error("Zadaj LTHR.")
        return
    speed = None
    if pace_text.strip():
        if sport == "bike":
            st.error("Tempo sa pre bicykel nepoužíva.")
            return
        try:
            speed = parse_pace(pace_text)
        except ValueError as exc:
            st.error(str(exc))
            return
    try:
        data = ThresholdIn(sport=sport, valid_from=valid_from, lthr=lthr, threshold_speed=speed)
        with _db.session() as session:
            settings_service.add_threshold(session, data, today=_db.today())
    except (ServiceError, ValidationError) as exc:
        st.error(str(exc))
    else:
        _saved(f"Prah ({sport_label(sport)}, od {fmt_date(valid_from)}) uložený.")


def zone_preview(cfg: SettingsDTO) -> None:
    """Zone tables for today's thresholds: HR bounds in bpm per sport, run pace bounds as min/km."""
    st.markdown("##### Zóny podľa dnešných prahov")
    tables = [(f"Tepové zóny – {sport_label(s).lower()}", zones, "hr") for s, zones in cfg.hr_zones.items()]
    if cfg.pace_zones:
        tables.append(("Tempové zóny – beh", cfg.pace_zones, "pace"))
    if not tables:
        st.info("Bez platného prahu sa zóny nedajú zobraziť.")
        return
    for col, (title, zones, kind) in zip(st.columns(len(tables)), tables, strict=True):
        col.markdown(f"**{title}**")
        col.dataframe(
            pd.DataFrame(
                [{"Zóna": f"Z{z.zone}", "Rozsah": fmt_zone_range(z.lower, z.upper, kind)} for z in zones]
            ),
            hide_index=True,
            width="stretch",
        )
