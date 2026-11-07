from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Observation, Station

TREND_DELTA_CM = 5.0  # perubahan < 5 cm dari 3 bacaan terakhir dianggap stabil


def latest_observation(db: Session, station_id: int) -> Observation | None:
    q = (select(Observation).where(Observation.station_id == station_id)
         .order_by(Observation.observed_at.desc(), Observation.id.desc()).limit(1))
    return db.scalars(q).first()


def is_stale(obs: Observation | None, now: datetime) -> bool:
    return obs is None or now - obs.observed_at > timedelta(minutes=settings.observation_stale_minutes)


def level_status(station: Station, obs: Observation | None, now: datetime) -> str:
    if obs is None:
        return "tidak_ada_data"
    # nilai terakhir yang sudah lama tidak boleh dibaca sebagai kondisi sekarang
    if is_stale(obs, now):
        return "data_kedaluwarsa"
    if obs.level_cm >= station.danger_cm:
        return "bahaya"
    if obs.level_cm >= station.warning_cm:
        return "waspada"
    return "normal"


def trend_direction(readings: list[Observation]) -> str:
    """readings urut waktu naik."""
    if len(readings) < 2:
        return "belum_cukup_data"
    recent = readings[-3:]
    delta = recent[-1].level_cm - recent[0].level_cm
    if delta > TREND_DELTA_CM:
        return "naik"
    if delta < -TREND_DELTA_CM:
        return "turun"
    return "stabil"


def station_view(db: Session, station: Station, now: datetime) -> dict:
    obs = latest_observation(db, station.id)
    return {
        **{c: getattr(station, c) for c in (
            "id", "name", "region_id", "lat", "lng", "is_upstream", "river_name", "warning_cm", "danger_cm")},
        "latest": obs,
        "status": level_status(station, obs, now),
        "stale": is_stale(obs, now),
        **condition_info(station, now),
    }


def condition_info(station: Station, now: datetime) -> dict:
    """Kondisi sungai yang ditetapkan pos pantau + penanda 'belum diperbarui' (PRD §17.2)."""
    stale = station.condition_at is None or now - station.condition_at > timedelta(hours=settings.condition_stale_hours)
    return {"condition": station.condition or "normal", "condition_at": station.condition_at,
            "condition_by": station.condition_by, "condition_stale": stale}
