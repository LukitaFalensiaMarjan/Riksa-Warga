from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import (
    city_scope_ids,
    ensure_city_access,
    ensure_region_access,
    operational_user,
    require_role,
)
from app.db import get_db, utcnow
from app.models import (
    Region,
    Resident,
    ResidentStatusLog,
    Role,
    SafetyStatus,
    Shelter,
    ShelterCheckin,
    ShelterStatus,
    StatusSource,
    User,
)
from app.schemas import CheckinIn, CheckinOut, NoteIn, ShelterCreate, ShelterOut, ShelterStatusIn
from app.services import notifier
from app.services.residents import active_incident_for_region
from app.services.shelter_alerts import alternatives, announce_unavailable

router = APIRouter(prefix="/shelters", tags=["shelter"])
coordinator = require_role(Role.KOORDINATOR)  # shelter = sumber daya kota: koordinator mengelola se-kota
SAR_OR_COORD = require_role(Role.KOORDINATOR, Role.TIM_SAR)


def _get(db: Session, me: User, shelter_id: int) -> Shelter:
    shelter = db.get(Shelter, shelter_id)
    if shelter is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shelter tidak ditemukan")
    if me.role == Role.KOORDINATOR:
        ensure_region_access(db, me, shelter.region_id)
    else:
        ensure_city_access(db, me, shelter.region_id)
    return shelter


def occupancy(db: Session) -> dict[int, int]:
    rows = db.execute(select(ShelterCheckin.shelter_id, func.sum(ShelterCheckin.people_count))
                      .group_by(ShelterCheckin.shelter_id)).all()
    return {sid: int(n or 0) for sid, n in rows}


@router.get("", response_model=list[ShelterOut])
def list_shelters(db: Session = Depends(get_db), me: User = Depends(operational_user)):
    q = select(Shelter).where(Shelter.region_id.in_(city_scope_ids(db, me.region_id))).order_by(Shelter.id)
    if me.role != Role.KOORDINATOR:  # selain koordinator: hanya titik aman terverifikasi (PRD §12.1)
        q = q.where(Shelter.is_verified.is_(True))
    rows = db.scalars(q).all()
    occ = occupancy(db)
    return [{**ShelterOut.model_validate(s).model_dump(), "occupancy": occ.get(s.id, 0)} for s in rows]


@router.post("/{shelter_id}/checkin", response_model=CheckinOut, status_code=status.HTTP_201_CREATED)
def checkin(shelter_id: int, body: CheckinIn, background: BackgroundTasks, db: Session = Depends(get_db),
            me: User = Depends(SAR_OR_COORD)):
    shelter = db.get(Shelter, shelter_id)
    if shelter is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shelter tidak ditemukan")
    ensure_city_access(db, me, shelter.region_id)
    now = utcnow()
    if body.resident_id is not None:
        resident = db.get(Resident, body.resident_id)
        if resident is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Warga tidak ditemukan")
        incident = active_incident_for_region(db, resident.region_id)
        db.add(ResidentStatusLog(resident_id=resident.id, incident_id=incident.id if incident else None,
                                 status=SafetyStatus.TIBA_DI_TITIK_AMAN,
                                 source=StatusSource.PETUGAS if me.role == Role.TIM_SAR
                                 else StatusSource.KOORDINATOR,
                                 note=f"Check-in di {shelter.name}", updated_by=me.id, created_at=now))
    row = ShelterCheckin(shelter_id=shelter.id, resident_id=body.resident_id, name=body.name,
                         people_count=body.people_count, checked_by=me.id, created_at=now)
    db.add(row)
    db.flush()
    total = occupancy(db).get(shelter.id, 0)
    full_alert = None
    if shelter.capacity and total >= shelter.capacity and shelter.status != ShelterStatus.PENUH:
        log_action(db, actor_id=me.id, action="shelter.status", entity_type="shelter", entity_id=shelter.id,
                   old={"status": shelter.status.value}, new={"status": ShelterStatus.PENUH.value},
                   reason=f"Otomatis: {total}/{shelter.capacity} orang")
        shelter.status, shelter.updated_at = ShelterStatus.PENUH, now
        full_alert = announce_unavailable(db, shelter, me, f"Otomatis: {total}/{shelter.capacity} orang", now)
    log_action(db, actor_id=me.id, action="shelter.checkin", entity_type="shelter", entity_id=shelter.id,
               new={"people": body.people_count, "resident_id": body.resident_id, "total": total})
    db.commit()
    notifier.schedule(background, db, [full_alert])
    return row


@router.get("/{shelter_id}/checkins", response_model=list[CheckinOut])
def list_checkins(shelter_id: int, db: Session = Depends(get_db),
                  me: User = Depends(coordinator)):
    _get(db, me, shelter_id)
    return db.scalars(select(ShelterCheckin).where(ShelterCheckin.shelter_id == shelter_id)
                      .order_by(ShelterCheckin.id.desc())).all()


@router.post("", response_model=ShelterOut, status_code=status.HTTP_201_CREATED)
def create_shelter(body: ShelterCreate, db: Session = Depends(get_db), me: User = Depends(coordinator)):
    if db.get(Region, body.region_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Wilayah tidak ditemukan")
    if me.role == Role.KOORDINATOR:
        ensure_region_access(db, me, body.region_id)
    else:
        ensure_city_access(db, me, body.region_id)
    shelter = Shelter(**body.model_dump(), status=ShelterStatus.TERSEDIA, is_verified=False, updated_at=utcnow())
    db.add(shelter)
    db.flush()
    log_action(db, actor_id=me.id, action="shelter.create", entity_type="shelter", entity_id=shelter.id,
               new=body.model_dump(mode="json"))
    db.commit()
    return shelter


@router.post("/{shelter_id}/verify", response_model=ShelterOut)
def verify_shelter(shelter_id: int, body: NoteIn, db: Session = Depends(get_db), me: User = Depends(coordinator)):
    shelter = _get(db, me, shelter_id)
    now = utcnow()
    shelter.is_verified, shelter.verified_at, shelter.verified_by, shelter.updated_at = True, now, me.id, now
    log_action(db, actor_id=me.id, action="shelter.verify", entity_type="shelter", entity_id=shelter.id,
               new={"is_verified": True}, reason=body.note)
    db.commit()
    return shelter


@router.post("/{shelter_id}/status", response_model=ShelterOut)
def update_shelter_status(shelter_id: int, body: ShelterStatusIn, background: BackgroundTasks,
                          db: Session = Depends(get_db), me: User = Depends(coordinator)):
    """Penuh/tidak dapat digunakan -> kabar otomatis ke warga sekitar, Tim SAR, pos pantau + alternatif (FR-074)."""
    shelter = _get(db, me, shelter_id)
    old = shelter.status
    now = utcnow()
    shelter.status, shelter.updated_at = body.status, now
    log_action(db, actor_id=me.id, action="shelter.status", entity_type="shelter", entity_id=shelter.id,
               old={"status": old.value}, new={"status": body.status.value}, reason=body.note)
    alert = None
    if body.status in (ShelterStatus.PENUH, ShelterStatus.TIDAK_DAPAT_DIGUNAKAN) and body.status != old:
        alert = announce_unavailable(db, shelter, me, body.note, now)
    db.commit()
    notifier.schedule(background, db, [alert])
    return shelter


@router.get("/{shelter_id}/alternatives")
def shelter_alternatives(shelter_id: int, db: Session = Depends(get_db), me: User = Depends(operational_user)):
    shelter = _get(db, me, shelter_id)
    return {"shelter_id": shelter.id, "status": shelter.status.value, "alternatives": alternatives(db, shelter)}
