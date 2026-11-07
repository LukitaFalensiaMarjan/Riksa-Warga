"""Simulator tinggi air untuk demo (PRD FR-012, §21.1). Semua pembacaan berlabel SIMULATION dan hanya
dipakai kejadian simulasi: tidak pernah tercampur dengan data nyata."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.models import Alert, Observation, RiverCondition, SourceMode, Station, User
from app.services import engine

START_CM = 40.0


def next_level(station: Station, last: float | None, scenario: str) -> float:
    """shortcut: satu langkah linear (12% ambang waspada, min. 5 cm); skenario hujan nyata menyusul."""
    if last is None:
        return START_CM
    step = max(5.0, station.warning_cm * 0.12)
    value = last + step if scenario == "naik" else last - step
    return round(min(max(value, 0.0), station.danger_cm * 1.3), 1)


def condition_for(station: Station, level: float) -> RiverCondition:
    if level >= station.danger_cm:
        return RiverCondition.MELUAP
    if level >= station.warning_cm:
        return RiverCondition.ARUS_DERAS
    return RiverCondition.NAIK if level > START_CM else RiverCondition.NORMAL


def step(db: Session, station: Station, scenario: str, actor: User, now: datetime) -> tuple[Observation, list[Alert]]:
    """Tambah satu pembacaan SIMULASI lalu jalankan mesin aturan (alert risiko pos pantau bila lintas ambang).
    Pemanggil memegang engine.LOCK dan commit."""
    last = db.scalars(select(Observation).where(
        Observation.station_id == station.id, Observation.source_mode == SourceMode.SIMULATION)
        .order_by(Observation.observed_at.desc(), Observation.id.desc()).limit(1)).first()
    level = next_level(station, None if last is None else last.level_cm, scenario)
    obs = Observation(station_id=station.id, level_cm=level, river_condition=condition_for(station, level),
                      note="SIMULASI", source_mode=SourceMode.SIMULATION, observed_at=now, received_at=now,
                      reported_by=actor.id)
    db.add(obs)
    db.flush()
    alerts = engine.process_observation(db, station, obs, now)
    log_action(db, actor_id=actor.id, action="simulation.step", entity_type="observation", entity_id=obs.id,
               new={"station_id": station.id, "level_cm": level, "scenario": scenario})
    return obs, alerts
