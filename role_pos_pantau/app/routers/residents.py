from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import ensure_region_access, get_current_user, region_scope_ids, require_role, user_scope_ids
from app.db import get_db, utcnow
from app.models import (Incident, Region, Resident, ResidentStatusLog, RiverLevel, Role, SafetyStatus, Station,
                        StatusSource, User)
from app.schemas import (
    NearStationIn,
    HelpRequestOut,
    LocationIn,
    ResidentCreate,
    ResidentDetail,
    ResidentOut,
    ResidentUpdate,
    SelfStatusIn,
    StatusLogOut,
    StatusSummaryOut,
    StatusUpdateIn,
)
from app.services import disaster
from app.services.residents import (
    active_incident_for_region,
    help_queue,
    latest_status_map,
    resident_view,
    status_summary,
)

router = APIRouter(tags=["warga"])
coordinator = require_role(Role.KOORDINATOR)
warga_only = require_role(Role.WARGA)  # PRD v2: lokasi, status keselamatan, dan izin = fitur Warga


def _scoped_residents(db: Session, me: User, region_id: int | None = None) -> list[Resident]:
    q = select(Resident).order_by(Resident.name, Resident.id)
    scope = user_scope_ids(db, me)
    if scope is not None:
        q = q.where(Resident.region_id.in_(scope))
    if region_id is not None:
        ensure_region_access(db, me, region_id)
        q = q.where(Resident.region_id.in_(region_scope_ids(db, region_id)))
    return list(db.scalars(q))


def _get(db: Session, me: User, resident_id: int) -> Resident:
    resident = db.get(Resident, resident_id)
    if resident is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Warga tidak ditemukan")
    ensure_region_access(db, me, resident.region_id)
    return resident


def _check_consent(vulnerability: list, notes: str | None, consent: bool) -> None:
    if (vulnerability or notes) and not consent:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Data kerentanan/kebutuhan khusus wajib disertai persetujuan (consent)")


def _resolve_incident(db: Session, incident_id: int | None, region_id: int) -> int | None:
    if incident_id is None:
        incident = active_incident_for_region(db, region_id)
        return incident.id if incident else None
    if db.get(Incident, incident_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Kejadian tidak ditemukan")
    return incident_id


# ---------- Koordinator ----------

@router.get("/residents", response_model=list[ResidentOut])
def list_residents(
    region_id: int | None = None,
    q: str | None = Query(None, max_length=120),
    status_: SafetyStatus | None = Query(None, alias="status"),
    vulnerable: bool | None = None,
    incident_id: int | None = None,
    db: Session = Depends(get_db),
    me: User = Depends(coordinator),
):
    residents = _scoped_residents(db, me, region_id)
    if q:
        residents = [r for r in residents if q.lower() in r.name.lower()]
    latest = latest_status_map(db, [r.id for r in residents], incident_id)
    now, cache = utcnow(), {}
    out = [resident_view(r, latest.get(r.id), hide_live=not disaster.live_location_visible(db, r.region_id, now, cache))
           for r in residents]
    if vulnerable is not None:
        out = [o for o in out if bool(o["vulnerability"]) == vulnerable]
    if status_:
        out = [o for o in out if o["latest_status"] == status_]
    return out


@router.get("/residents/summary", response_model=StatusSummaryOut)
def residents_summary(region_id: int | None = None, incident_id: int | None = None,
                      db: Session = Depends(get_db), me: User = Depends(coordinator)):
    return status_summary(db, _scoped_residents(db, me, region_id), incident_id)


@router.get("/help-requests", response_model=list[HelpRequestOut])
def help_requests(incident_id: int | None = None, db: Session = Depends(get_db), me: User = Depends(coordinator)):
    now, cache = utcnow(), {}
    return help_queue(db, _scoped_residents(db, me), incident_id,
                      live_ok=lambda r: disaster.live_location_visible(db, r.region_id, now, cache))


@router.post("/residents", response_model=ResidentDetail, status_code=status.HTTP_201_CREATED)
def create_resident(body: ResidentCreate, db: Session = Depends(get_db), me: User = Depends(coordinator)):
    if db.get(Region, body.region_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Wilayah tidak ditemukan")
    ensure_region_access(db, me, body.region_id)
    _check_consent(body.vulnerability, body.assistance_notes, body.consent)
    if body.user_id is not None:
        if db.get(User, body.user_id) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Akun tidak ditemukan")
        if db.scalar(select(Resident.id).where(Resident.user_id == body.user_id)):
            raise HTTPException(status.HTTP_409_CONFLICT, "Akun sudah terhubung ke data warga lain")
    resident = Resident(**body.model_dump(mode="json"), created_by=me.id)
    db.add(resident)
    db.flush()
    # isi catatan sensitif tidak disalin ke audit log, cukup nama field
    log_action(db, actor_id=me.id, action="resident.create", entity_type="resident", entity_id=resident.id,
               new={"fields": sorted(k for k, v in body.model_dump().items() if v not in (None, [], False))})
    db.commit()
    return resident_view(resident, None, detail=True)


@router.get("/residents/{resident_id}", response_model=ResidentDetail)
def get_resident(resident_id: int, db: Session = Depends(get_db), me: User = Depends(coordinator)):
    resident = _get(db, me, resident_id)
    log_action(db, actor_id=me.id, action="resident.view_detail", entity_type="resident", entity_id=resident.id)
    db.commit()
    return resident_view(resident, latest_status_map(db, [resident.id]).get(resident.id), detail=True,
                         hide_live=not disaster.live_location_visible(db, resident.region_id, utcnow()))


@router.patch("/residents/{resident_id}", response_model=ResidentDetail)
def update_resident(resident_id: int, body: ResidentUpdate, db: Session = Depends(get_db),
                    me: User = Depends(coordinator)):
    resident = _get(db, me, resident_id)
    changes = body.model_dump(exclude_unset=True, mode="json")
    if "region_id" in changes:
        if db.get(Region, changes["region_id"]) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Wilayah tidak ditemukan")
        ensure_region_access(db, me, changes["region_id"])
    _check_consent(changes.get("vulnerability", resident.vulnerability),
                   changes.get("assistance_notes", resident.assistance_notes),
                   changes.get("consent", resident.consent))
    for key, value in changes.items():
        setattr(resident, key, value)
    log_action(db, actor_id=me.id, action="resident.update", entity_type="resident", entity_id=resident.id,
               new={"fields": sorted(changes)})
    db.commit()
    return resident_view(resident, latest_status_map(db, [resident.id]).get(resident.id), detail=True,
                         hide_live=not disaster.live_location_visible(db, resident.region_id, utcnow()))


@router.post("/residents/{resident_id}/status", response_model=StatusLogOut, status_code=status.HTTP_201_CREATED)
def record_status(resident_id: int, body: StatusUpdateIn, db: Session = Depends(get_db),
                  me: User = Depends(coordinator)):
    resident = _get(db, me, resident_id)
    log = ResidentStatusLog(
        resident_id=resident.id, incident_id=_resolve_incident(db, body.incident_id, resident.region_id),
        status=body.status, source=body.source, need_type=body.need_type, note=body.note,
        updated_by=me.id, created_at=utcnow(),
    )
    db.add(log)
    db.flush()
    log_action(db, actor_id=me.id, action="resident.status", entity_type="resident", entity_id=resident.id,
               new={"status": body.status.value, "source": body.source.value, "incident_id": log.incident_id},
               reason=body.note)
    db.commit()
    return log


@router.get("/residents/{resident_id}/statuses", response_model=list[StatusLogOut])
def status_history(resident_id: int, db: Session = Depends(get_db), me: User = Depends(coordinator)):
    resident = _get(db, me, resident_id)
    return db.scalars(select(ResidentStatusLog).where(ResidentStatusLog.resident_id == resident.id)
                      .order_by(ResidentStatusLog.id)).all()


# ---------- Warga (data sendiri) ----------

def _my_resident(db: Session, me: User) -> Resident:
    resident = db.scalar(select(Resident).where(Resident.user_id == me.id))
    if resident is None:
        resident = Resident(name=me.name, region_id=me.region_id, user_id=me.id, has_smartphone=True,
                            vulnerability=[], consent=False, created_by=me.id)
        db.add(resident)
        db.flush()
    return resident


@router.get("/me/resident", response_model=ResidentDetail)
def my_resident(db: Session = Depends(get_db), me: User = Depends(warga_only)):
    resident = _my_resident(db, me)
    db.commit()
    return resident_view(resident, latest_status_map(db, [resident.id]).get(resident.id), detail=True)


@router.post("/me/status", response_model=StatusLogOut, status_code=status.HTTP_201_CREATED)
def self_status(body: SelfStatusIn, db: Session = Depends(get_db), me: User = Depends(warga_only)):
    resident = _my_resident(db, me)
    # "Saya Aman" = laporan mandiri, tidak pernah langsung aman terverifikasi (PRD §12.2)
    new_status = SafetyStatus.AMAN_MANDIRI if body.status == "aman" else SafetyStatus.BUTUH_BANTUAN
    now = utcnow()
    share = body.lat is not None and disaster.has_location_consent(resident)  # tanpa izin, lokasi diabaikan
    log = ResidentStatusLog(
        resident_id=resident.id, incident_id=_resolve_incident(db, body.incident_id, resident.region_id),
        status=new_status, source=StatusSource.MANDIRI, need_type=body.need_type, note=body.note,
        lat=body.lat if share else None, lng=body.lng if share else None, updated_by=me.id, created_at=now,
    )
    if share:  # lokasi dibagikan bersama status, atas tindakan warga sendiri
        resident.last_lat, resident.last_lng, resident.last_location_at = body.lat, body.lng, now
    db.add(log)
    db.flush()
    log_action(db, actor_id=me.id, action="resident.self_status", entity_type="resident", entity_id=resident.id,
               new={"status": new_status.value, "incident_id": log.incident_id, "lokasi": body.lat is not None})
    db.commit()
    return log


@router.post("/me/location", response_model=ResidentDetail)
def share_location(body: LocationIn, db: Session = Depends(get_db), me: User = Depends(warga_only)):
    """Warga membagikan lokasi terkini / menyimpan lokasi rumah. Hanya terlihat koordinator wilayahnya."""
    resident = _my_resident(db, me)
    if body.kind == "terkini" and not disaster.has_location_consent(resident):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Izin berbagi lokasi belum diberikan (POST /me/location-consent)")
    if body.kind == "rumah":
        resident.home_lat, resident.home_lng = body.lat, body.lng
    else:
        resident.last_lat, resident.last_lng, resident.last_location_at = body.lat, body.lng, utcnow()
    # koordinat tidak disalin ke audit log, cukup jenisnya
    log_action(db, actor_id=me.id, action="resident.location", entity_type="resident", entity_id=resident.id,
               new={"kind": body.kind})
    db.commit()
    return resident_view(resident, latest_status_map(db, [resident.id]).get(resident.id), detail=True)


# ---------- Izin lokasi sekali + Mode Bencana (PRD v2 §8) ----------

def _near_station(db: Session, resident: Resident, now) -> dict | None:
    """Kondisi live pos pantau terdekat pilihan warga: dari angka tinggi air, cadangan kondisi yang diatur pos."""
    from app.services.monitoring import latest_observation, level_status
    st = db.get(Station, resident.near_station_id) if resident.near_station_id else None
    if st is None:
        return None
    obs = latest_observation(db, st.id)
    status_ = {"bahaya": "meluap"}.get(level_status(st, obs, now), level_status(st, obs, now))
    if status_ not in ("normal", "waspada", "meluap"):
        cond = disaster.latest_condition(db, st.id, now)
        if cond is not None and not cond["stale"]:
            status_ = {RiverLevel.NORMAL: "normal", RiverLevel.WASPADA: "waspada"}.get(cond["status"], "meluap")
    return {"id": st.id, "name": st.name, "river_name": st.river_name, "status": status_,
            "level_cm": obs.level_cm if obs else None, "warning_cm": st.warning_cm, "danger_cm": st.danger_cm}


def _consent_view(db: Session, resident: Resident) -> dict:
    now = utcnow()
    state = disaster.area_disaster(db, resident.region_id, now)
    return {"granted": disaster.has_location_consent(resident), "granted_at": resident.location_consent_at,
            "revoked_at": resident.location_revoked_at, "near_station": _near_station(db, resident, now),
            "disaster_mode": {"active": state["active"], "since": state["since"], "reasons": state["reasons"]},
            "note": "Izin berlaku sampai Anda mencabutnya. Lokasi hanya dipakai saat Mode Bencana di area Anda "
                    "dan tidak pernah dikirim lewat pesan Telegram/SMS."}


@router.get("/me/location-consent")
def my_location_consent(db: Session = Depends(get_db), me: User = Depends(warga_only)):
    resident = _my_resident(db, me)
    db.commit()
    return _consent_view(db, resident)


@router.post("/me/location-consent", status_code=status.HTTP_201_CREATED)
def grant_location_consent(body: NearStationIn | None = None, db: Session = Depends(get_db),
                           me: User = Depends(warga_only)):
    """Izin SEKALI: panggilan berulang tidak mengubah waktu izin pertama. station_id = pos terdekat (boleh diubah)."""
    resident = _my_resident(db, me)
    if body is not None and body.station_id is not None:
        if db.get(Station, body.station_id) is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Pos pantau tidak ditemukan")
        resident.near_station_id = body.station_id
    already = disaster.has_location_consent(resident)
    disaster.grant_consent(resident, utcnow())
    if not already:
        log_action(db, actor_id=me.id, action="location.consent", entity_type="resident", entity_id=resident.id)
    db.commit()
    return _consent_view(db, resident)


@router.delete("/me/location-consent")
def revoke_location_consent(db: Session = Depends(get_db), me: User = Depends(warga_only)):
    resident = _my_resident(db, me)
    disaster.revoke_consent(resident, utcnow())
    log_action(db, actor_id=me.id, action="location.revoke", entity_type="resident", entity_id=resident.id)
    db.commit()
    return _consent_view(db, resident)
