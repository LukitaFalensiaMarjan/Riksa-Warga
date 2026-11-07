from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import area_scope_ids, ensure_region_access, get_current_user, require_role, user_scope_ids
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
from app.services.residents import active_incident_for_region

router = APIRouter(prefix="/shelters", tags=["shelter"])
coordinator = require_role(Role.KOORDINATOR, Role.ADMIN)


def _get(db: Session, me: User, shelter_id: int) -> Shelter:
    shelter = db.get(Shelter, shelter_id)
    if shelter is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shelter tidak ditemukan")
    ensure_region_access(db, me, shelter.region_id)
    return shelter


def occupancy(db: Session) -> dict[int, int]:
    rows = db.execute(select(ShelterCheckin.shelter_id, func.sum(ShelterCheckin.people_count))
                      .group_by(ShelterCheckin.shelter_id)).all()
    return {sid: int(n or 0) for sid, n in rows}


@router.get("", response_model=list[ShelterOut])
def list_shelters(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    q = select(Shelter).order_by(Shelter.id)
    if me.role in (Role.KOORDINATOR, Role.ADMIN):
        scope = user_scope_ids(db, me)
        rows = db.scalars(q if scope is None else q.where(Shelter.region_id.in_(scope))).all()
    else:  # warga, relawan & pos pantau: hanya titik aman terverifikasi di kelurahannya
        rows = db.scalars(q.where(Shelter.is_verified.is_(True),
                                  Shelter.region_id.in_(area_scope_ids(db, me.region_id)))).all()
    occ = occupancy(db)
    return [{**ShelterOut.model_validate(s).model_dump(), "occupancy": occ.get(s.id, 0)} for s in rows]


@router.post("/{shelter_id}/checkin", response_model=CheckinOut, status_code=status.HTTP_201_CREATED)
def checkin(shelter_id: int, body: CheckinIn, db: Session = Depends(get_db),
            me: User = Depends(require_role(Role.KOORDINATOR, Role.ADMIN, Role.RELAWAN, Role.PETUGAS))):
    shelter = db.get(Shelter, shelter_id)
    if shelter is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Shelter tidak ditemukan")
    if me.role != Role.ADMIN and shelter.region_id not in area_scope_ids(db, me.region_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Di luar kelurahan Anda")
    now = utcnow()
    if body.resident_id is not None:
        resident = db.get(Resident, body.resident_id)
        if resident is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Warga tidak ditemukan")
        incident = active_incident_for_region(db, resident.region_id)
        db.add(ResidentStatusLog(resident_id=resident.id, incident_id=incident.id if incident else None,
                                 status=SafetyStatus.TIBA_DI_TITIK_AMAN,
                                 source=StatusSource.PETUGAS if me.role in (Role.RELAWAN, Role.PETUGAS)
                                 else StatusSource.KOORDINATOR,
                                 note=f"Check-in di {shelter.name}", updated_by=me.id, created_at=now))
    row = ShelterCheckin(shelter_id=shelter.id, resident_id=body.resident_id, name=body.name,
                         people_count=body.people_count, checked_by=me.id, created_at=now)
    db.add(row)
    db.flush()
    total = occupancy(db).get(shelter.id, 0)
    if shelter.capacity and total >= shelter.capacity and shelter.status != ShelterStatus.PENUH:
        log_action(db, actor_id=me.id, action="shelter.status", entity_type="shelter", entity_id=shelter.id,
                   old={"status": shelter.status.value}, new={"status": ShelterStatus.PENUH.value},
                   reason=f"Otomatis: {total}/{shelter.capacity} orang")
        shelter.status, shelter.updated_at = ShelterStatus.PENUH, now
    log_action(db, actor_id=me.id, action="shelter.checkin", entity_type="shelter", entity_id=shelter.id,
               new={"people": body.people_count, "resident_id": body.resident_id, "total": total})
    db.commit()
    return row


@router.get("/{shelter_id}/checkins", response_model=list[CheckinOut])
def list_checkins(shelter_id: int, db: Session = Depends(get_db),
                  me: User = Depends(require_role(Role.KOORDINATOR, Role.ADMIN))):
    _get(db, me, shelter_id)
    return db.scalars(select(ShelterCheckin).where(ShelterCheckin.shelter_id == shelter_id)
                      .order_by(ShelterCheckin.id.desc())).all()


@router.post("", response_model=ShelterOut, status_code=status.HTTP_201_CREATED)
def create_shelter(body: ShelterCreate, db: Session = Depends(get_db), me: User = Depends(coordinator)):
    if db.get(Region, body.region_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Wilayah tidak ditemukan")
    ensure_region_access(db, me, body.region_id)
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
def update_shelter_status(shelter_id: int, body: ShelterStatusIn, db: Session = Depends(get_db),
                          me: User = Depends(coordinator)):
    shelter = _get(db, me, shelter_id)
    old = shelter.status
    shelter.status, shelter.updated_at = body.status, utcnow()
    log_action(db, actor_id=me.id, action="shelter.status", entity_type="shelter", entity_id=shelter.id,
               old={"status": old.value}, new={"status": body.status.value}, reason=body.note)
    db.commit()
    return shelter
