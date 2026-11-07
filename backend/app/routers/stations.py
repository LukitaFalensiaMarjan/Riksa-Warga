from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import area_scope_ids, ensure_region_access, get_current_user, require_role
from app.db import get_db, to_utc_naive, utcnow
from app.models import Observation, Region, Role, Station, User
from app.schemas import ObservationCreate, ObservationOut, StationCreate, StationOut, TrendOut
from app.services import engine, notifier
from app.services.monitoring import is_stale, latest_observation, level_status, station_view, trend_direction

router = APIRouter(prefix="/stations", tags=["pos pantau"])
observer = require_role(Role.POS_PANTAU, Role.KOORDINATOR, Role.ADMIN)
coordinator = require_role(Role.KOORDINATOR, Role.ADMIN)


def _get_visible(db: Session, me: User, station_id: int) -> Station:
    station = db.get(Station, station_id)
    if station is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pos pantau tidak ditemukan")
    if me.role != Role.ADMIN and station.region_id not in area_scope_ids(db, me.region_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Di luar wilayah kewenangan")
    return station


@router.get("", response_model=list[StationOut])
def list_stations(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    q = select(Station).order_by(Station.id)
    if me.role != Role.ADMIN:
        q = q.where(Station.region_id.in_(area_scope_ids(db, me.region_id)))
    now = utcnow()
    return [station_view(db, s, now) for s in db.scalars(q)]


@router.post("", response_model=StationOut, status_code=status.HTTP_201_CREATED)
def create_station(body: StationCreate, db: Session = Depends(get_db), me: User = Depends(coordinator)):
    if db.get(Region, body.region_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Wilayah tidak ditemukan")
    ensure_region_access(db, me, body.region_id)
    station = Station(**body.model_dump())
    db.add(station)
    db.flush()
    log_action(db, actor_id=me.id, action="station.create", entity_type="station", entity_id=station.id,
               new=body.model_dump(mode="json"))
    db.commit()
    return station_view(db, station, utcnow())


@router.post("/{station_id}/observations", response_model=ObservationOut, status_code=status.HTTP_201_CREATED)
@engine.locked
def add_observation(station_id: int, body: ObservationCreate, background: BackgroundTasks,
                    db: Session = Depends(get_db), me: User = Depends(observer)):
    station = db.get(Station, station_id)
    if station is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pos pantau tidak ditemukan")
    ensure_region_access(db, me, station.region_id)  # pos pantau hanya mengisi pos di wilayah tugasnya
    now = utcnow()
    observed_at = to_utc_naive(body.observed_at) if body.observed_at else now
    if observed_at > now + timedelta(minutes=5):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Waktu pengamatan tidak boleh di masa depan")

    obs = Observation(station_id=station.id, level_cm=body.level_cm, river_condition=body.river_condition,
                      note=body.note, source_mode=body.source_mode, observed_at=observed_at, received_at=now,
                      reported_by=me.id)
    db.add(obs)
    db.flush()
    alerts = engine.process_observation(db, station, obs, now)
    log_action(db, actor_id=me.id, action="observation.create", entity_type="observation", entity_id=obs.id,
               new={"station_id": station.id, "level_cm": obs.level_cm, "source_mode": obs.source_mode.value})
    db.commit()
    notifier.schedule(background, db, alerts)
    return obs


@router.get("/{station_id}/trend", response_model=TrendOut)
def station_trend(station_id: int, hours: int = Query(6, ge=1, le=72), db: Session = Depends(get_db),
                  me: User = Depends(get_current_user)):
    station = _get_visible(db, me, station_id)
    now = utcnow()
    readings = db.scalars(select(Observation).where(
        Observation.station_id == station.id, Observation.observed_at >= now - timedelta(hours=hours))
        .order_by(Observation.observed_at, Observation.id)).all()
    last = latest_observation(db, station.id)
    return {"station_id": station.id, "direction": trend_direction(list(readings)),
            "status": level_status(station, last, now), "stale": is_stale(last, now), "readings": readings}
