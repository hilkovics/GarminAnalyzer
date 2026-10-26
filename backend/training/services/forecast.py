"""Predictions (METRICS §11.5): glue only, `training.planning_forecast` computes."""

import datetime as dt
from dataclasses import asdict

from sqlmodel import Session

from training import planning_forecast
from training.coach import forecast as fc
from training.services.dto import ForecastDTO, OutlookDayDTO, SleepEffectDTO, SleepNoteDTO


def get_forecast(session: Session, today: dt.date) -> ForecastDTO:
    effect = planning_forecast.sleep_effect(session)
    note = fc.sleep_note(effect, planning_forecast.last_night_sleep(session, today))
    outlook = planning_forecast.outlook(session, today)
    return ForecastDTO(
        date=today,
        sleep_effect=SleepEffectDTO(
            **asdict(effect), min_n=fc.MIN_ROWS, s_per_km_per_hour=effect.s_per_km_per_hour
        ),
        note=SleepNoteDTO(**asdict(note)) if note is not None else None,
        days=[
            OutlookDayDTO(
                date=d.day,
                readiness=d.readiness,
                band=d.band,
                load=d.load,
                tsb=d.tsb,
                **d.typical,
                available=d.day in outlook.available,
                best=d.day in outlook.best,
            )
            for d in outlook.days
        ],
    )
