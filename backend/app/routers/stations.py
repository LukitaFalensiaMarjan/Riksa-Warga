from datetime import timedelta

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import (
    ancestor_at_level,
    city_scope_ids,
    ensure_city_access,
    ensure_region_access,
    get_current_user,
    operational_user,
    require_role,
)
from app.db import get_db, to_utc_naive, utcnow
from app.models import AlertKind, AlertLevel, Observation, Region, RegionLevel, Role, Station, User, Verification
from app.schemas import ConditionIn, ObservationCreate, ObservationOut, StationCreate, StationOut, TrendOut
from app.services import engine, notifier
from app.services.alerting import emit
from app.services.messages import FOOTER, fmt_time
from app.services.monitoring import (
    condition_info,
    is_stale,
    latest_observation,
    level_status,
    station_view,
    trend_direction,
)
from app.services.simulator import generate_observation_for_station

router = APIRouter(prefix="/stations", tags=["pos pantau"])
pos_pantau_only = require_role(Role.POS_PANTAU)
coordinator = require_role(Role.KOORDINATOR)

COND_ACTION = {
    "waspada": "Pantau informasi, jauhi bantaran sungai, siapkan dokumen penting, obat, dan tas siaga.",
    "meluap": ("Air sungai meluap. Jauhi bantaran, segera menuju shelter aman terdekat sesuai arahan petugas, "
               "lalu buka aplikasi Riksa Warga dan laporkan Saya Aman / Butuh Bantuan."),
    "normal": "Kondisi kembali aman. Tetap pantau informasi.",
}


def _visible_station(db: Session, me: User, station_id: int) -> Station:
    station = db.get(Station, station_id)
    if station is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pos pantau tidak ditemukan")
    ensure_city_access(db, me, station.region_id)  # kondisi sungai terlihat se-kota (PRD §5.2)
    return station


@router.get("/live")
def live_stations(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    """Kondisi seluruh pos sungai se-kota + 10 bacaan terakhir; dipolling UI tiap beberapa detik."""
    now = utcnow()
    stations = db.scalars(select(Station).where(Station.region_id.in_(city_scope_ids(db, me.region_id)))
                          .order_by(Station.id)).all()
    results = []
    for s in stations:
        last = latest_observation(db, s.id)
        recent = db.scalars(select(Observation).where(Observation.station_id == s.id)
                            .order_by(Observation.observed_at.desc(), Observation.id.desc()).limit(10)).all()
        recent_sorted = list(reversed(recent))
        info = condition_info(s, now)
        by = db.get(User, s.condition_by) if s.condition_by else None
        results.append({
            "id": s.id, "name": s.name, "river_name": s.river_name or "Sungai di Bandung", "lat": s.lat, "lng": s.lng,
            "region_id": s.region_id, "is_upstream": s.is_upstream, "warning_cm": s.warning_cm,
            "danger_cm": s.danger_cm, "current_condition": info["condition"], "condition_at": info["condition_at"],
            "condition_by_name": by.name if by else None, "condition_stale": info["condition_stale"],
            "status": level_status(s, last, now), "trend": trend_direction(recent_sorted), "latest": last,
            "recent_readings": recent_sorted, "stale": is_stale(last, now),
        })
    return results


@router.get("", response_model=list[StationOut])
def list_stations(db: Session = Depends(get_db), me: User = Depends(operational_user)):
    q = select(Station).where(Station.region_id.in_(city_scope_ids(db, me.region_id))).order_by(Station.id)
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
                    db: Session = Depends(get_db), me: User = Depends(pos_pantau_only)):
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
                  me: User = Depends(operational_user)):
    station = _visible_station(db, me, station_id)
    now = utcnow()
    readings = db.scalars(select(Observation).where(
        Observation.station_id == station.id, Observation.observed_at >= now - timedelta(hours=hours))
        .order_by(Observation.observed_at, Observation.id)).all()
    last = latest_observation(db, station.id)
    return {"station_id": station.id, "direction": trend_direction(list(readings)),
            "status": level_status(station, last, now), "stale": is_stale(last, now), "readings": readings}


@router.post("/{station_id}/condition")
def set_condition(station_id: int, body: ConditionIn, background: BackgroundTasks, db: Session = Depends(get_db),
                  me: User = Depends(pos_pantau_only)):
    """Tiga tombol kondisi sungai (Normal / Waspada / Meluap), HANYA pos pantau (FR-020).

    Disimpan permanen, langsung tampil di semua role, dan memicu notifikasi aplikasi + Telegram + SMS
    saat berubah ke Waspada/Meluap (PRD §7.3). Meluap otomatis menyalakan Mode Bencana di area itu."""
    station = db.get(Station, station_id)
    if station is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pos pantau tidak ditemukan")
    ensure_region_access(db, me, station.region_id)

    now = utcnow()
    old = station.condition or "normal"
    new = body.condition
    station.condition, station.condition_at, station.condition_by = new, now, me.id
    obs = generate_observation_for_station(db, station, new)  # bacaan SIMULASI agar grafik mengikuti kondisi
    alert = None
    if new != old:
        area = ancestor_at_level(db, station.region_id, RegionLevel.KELURAHAN) or station.region_id
        area_name = db.get(Region, area).name
        label = new.upper()
        lines = [
            f"[RIKSA WARGA — SUNGAI {label}]",
            f"Pos: {station.name} ({station.river_name or 'sungai'})",
            f"Wilayah: {area_name}",
            f"Waktu: {fmt_time(now)}",
            f"Status: {label} — TERVERIFIKASI pos pantau ({me.name})",
            f"Sebelumnya: {old.upper()}. Tinggi air terakhir {obs.level_cm:.0f} cm (SIMULASI, bukan sensor nyata).",
        ]
        if body.note:
            lines.append(f"Catatan: {body.note.strip()}")
        lines += [f"Tindakan: {COND_ACTION[new]}", FOOTER]
        level = {"normal": AlertLevel.PANTAU, "waspada": AlertLevel.WASPADA, "meluap": AlertLevel.EVAKUASI}[new]
        alert = emit(db, kind=AlertKind.SUNGAI, level=level, verification=Verification.TERVERIFIKASI,
                     audience_region_id=area, station_id=station.id, message=chr(10).join(lines), created_by=me.id,
                     sms=new in ("waspada", "meluap"), reason=f"Kondisi sungai {old} -> {new} oleh {me.name}", now=now)
    log_action(db, actor_id=me.id, action="station.condition", entity_type="station", entity_id=station.id,
               old={"condition": old}, new={"condition": new, "level_cm_simulasi": obs.level_cm}, reason=body.note)
    db.commit()
    notifier.schedule(background, db, [alert])
    if alert is not None and new != "normal":
        msg = f"Kondisi {station.name} diubah ke {new.upper()}. Notifikasi aplikasi, Telegram, dan SMS dikirim."
    else:
        msg = f"Kondisi {station.name}: {new.upper()}" + ("" if new != old else " (tidak berubah)")
    return {"station_id": station.id, "condition": new, "changed": new != old, "level_cm": obs.level_cm,
            "status": level_status(station, obs, now),
            "condition_at": now, "notified": alert is not None, "message": msg}


@router.get("/{station_id}/condition")
def get_condition(station_id: int, db: Session = Depends(get_db), me: User = Depends(operational_user)):
    station = _visible_station(db, me, station_id)
    return {"station_id": station.id, **condition_info(station, utcnow())}
