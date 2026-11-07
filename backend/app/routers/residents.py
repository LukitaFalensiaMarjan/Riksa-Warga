from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import city_scope_ids, ensure_region_access, operational_user, region_scope_ids, require_role, user_scope_ids
from app.config import settings
from app.db import get_db, utcnow
from app.models import (
    AlertKind,
    FamilyMember,
    Incident,
    Region,
    Resident,
    ResidentStatusLog,
    Role,
    SafetyStatus,
    StatusSource,
    User,
)
from app.schemas import (
    ConsentIn,
    FamilyIn,
    FamilyOut,
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
from app.services import notifier
from app.services.alerting import emit
from app.services.disaster import hazard_zones, in_hazard, last_location_usable, mode_regions
from app.services.residents import (
    active_incident_for_region,
    help_queue,
    latest_status_map,
    resident_view,
    status_summary,
)

router = APIRouter(tags=["warga"])
coordinator = require_role(Role.KOORDINATOR, Role.ADMIN)
sar_or_coord = require_role(Role.KOORDINATOR, Role.ADMIN, Role.TIM_SAR, Role.POS_PANTAU)
warga_only = require_role(Role.WARGA)
CONSENT_VERSION = "v1"


def _scoped_residents(db: Session, me: User, region_id: int | None = None) -> list[Resident]:
    q = select(Resident).order_by(Resident.name, Resident.id)
    if me.role in (Role.TIM_SAR, Role.POS_PANTAU):
        scope = city_scope_ids(db, me.region_id)
    else:
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
    me: User = Depends(sar_or_coord),
):
    residents = _scoped_residents(db, me, region_id)
    if q:
        residents = [r for r in residents if q.lower() in r.name.lower()]
    latest = latest_status_map(db, [r.id for r in residents], incident_id)
    now, mode = utcnow(), mode_regions(db)
    out = [resident_view(r, latest.get(r.id), show_last=last_location_usable(r, mode, now)) for r in residents]
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
def help_requests(incident_id: int | None = None, db: Session = Depends(get_db), me: User = Depends(sar_or_coord)):
    return help_queue(db, _scoped_residents(db, me), incident_id)


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
    show = last_location_usable(resident, mode_regions(db), utcnow())
    return resident_view(resident, latest_status_map(db, [resident.id]).get(resident.id), detail=True, show_last=show)


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
    return resident_view(resident, latest_status_map(db, [resident.id]).get(resident.id), detail=True)


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


# ---------- Data keluarga (koordinator, FR-060) ----------

@router.get("/residents/{resident_id}/family", response_model=list[FamilyOut])
def list_family(resident_id: int, db: Session = Depends(get_db), me: User = Depends(coordinator)):
    resident = _get(db, me, resident_id)
    log_action(db, actor_id=me.id, action="family.view", entity_type="resident", entity_id=resident.id)  # data sensitif
    db.commit()
    return db.scalars(select(FamilyMember).where(FamilyMember.resident_id == resident.id).order_by(FamilyMember.id)).all()


@router.post("/residents/{resident_id}/family", response_model=FamilyOut, status_code=status.HTTP_201_CREATED)
def add_family(resident_id: int, body: FamilyIn, db: Session = Depends(get_db), me: User = Depends(coordinator)):
    resident = _get(db, me, resident_id)
    _check_consent([v.value for v in body.vulnerability], body.note, resident.consent)
    member = FamilyMember(resident_id=resident.id, created_by=me.id, created_at=utcnow(),
                          **body.model_dump(mode="json"))
    db.add(member)
    db.flush()
    log_action(db, actor_id=me.id, action="family.add", entity_type="resident", entity_id=resident.id,
               new={"anggota_id": member.id})  # isi catatan tidak disalin ke audit
    db.commit()
    return member


@router.delete("/residents/{resident_id}/family/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_family(resident_id: int, member_id: int, db: Session = Depends(get_db), me: User = Depends(coordinator)):
    resident = _get(db, me, resident_id)
    member = db.get(FamilyMember, member_id)
    if member is None or member.resident_id != resident.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Anggota keluarga tidak ditemukan")
    db.delete(member)
    log_action(db, actor_id=me.id, action="family.remove", entity_type="resident", entity_id=resident.id,
               new={"anggota_id": member_id})
    db.commit()


# ---------- Warga (data sendiri) ----------

def _my_resident(db: Session, me: User) -> Resident:
    resident = db.scalar(select(Resident).where(Resident.user_id == me.id))
    if resident is None:
        resident = Resident(name=me.name, region_id=me.region_id, user_id=me.id, has_smartphone=True,
                            vulnerability=[], consent=False, created_by=me.id)
        db.add(resident)
        db.flush()
    return resident


def _own_view(db: Session, resident: Resident) -> dict:
    return resident_view(resident, latest_status_map(db, [resident.id]).get(resident.id), detail=True, show_last=True)


@router.get("/me/resident", response_model=ResidentDetail)
def my_resident(db: Session = Depends(get_db), me: User = Depends(warga_only)):
    resident = _my_resident(db, me)
    db.commit()
    return _own_view(db, resident)


@router.get("/me/family", response_model=list[FamilyOut])
def my_family(db: Session = Depends(get_db), me: User = Depends(warga_only)):
    resident = _my_resident(db, me)
    db.commit()
    return db.scalars(select(FamilyMember).where(FamilyMember.resident_id == resident.id).order_by(FamilyMember.id)).all()


@router.get("/me/mode")
def my_mode(db: Session = Depends(get_db), me: User = Depends(warga_only)):
    """Apakah Mode Bencana aktif di area warga + sisa waktu menjawab (PRD §8, §9.3)."""
    resident = _my_resident(db, me)
    db.commit()
    now = utcnow()
    mode = mode_regions(db, now)
    since = mode.get(resident.region_id)
    if since is None:
        return {"active": False}
    answered = db.scalar(select(ResidentStatusLog.id).where(
        ResidentStatusLog.resident_id == resident.id, ResidentStatusLog.created_at >= since,
        ResidentStatusLog.source == StatusSource.MANDIRI).limit(1)) is not None
    left = max(0, int(settings.diduga_minutes * 60 - (now - since).total_seconds()))
    usable = last_location_usable(resident, mode, now)
    in_zone = in_hazard(resident.last_lat, resident.last_lng, hazard_zones(db)) if usable else None
    return {"active": True, "since": since, "answered": answered, "seconds_left": left,
            "diduga_minutes": settings.diduga_minutes, "consented": resident.location_consented,
            "in_hazard_zone": in_zone}


@router.post("/me/location/consent", response_model=ResidentDetail)
def location_consent(body: ConsentIn, db: Session = Depends(get_db), me: User = Depends(warga_only)):
    """Izin lokasi SEKALI seumur hidup (PRD §8). agree=false sama dengan mencabut."""
    resident = _my_resident(db, me)
    now = utcnow()
    if body.agree:
        resident.location_consent_at, resident.location_consent_version = now, body.version or CONSENT_VERSION
        resident.location_revoked_at = None
    else:
        resident.location_revoked_at = now
        resident.last_lat = resident.last_lng = resident.last_location_at = None  # pencabutan berlaku segera
    log_action(db, actor_id=me.id, action="location.consent" if body.agree else "location.revoke",
               entity_type="resident", entity_id=resident.id, new={"version": body.version})
    db.commit()
    return _own_view(db, resident)


@router.delete("/me/location/consent", response_model=ResidentDetail)
def revoke_location_consent(db: Session = Depends(get_db), me: User = Depends(warga_only)):
    return location_consent(ConsentIn(agree=False), db, me)


@router.post("/me/status", response_model=StatusLogOut, status_code=status.HTTP_201_CREATED)
def self_status(body: SelfStatusIn, background: BackgroundTasks, db: Session = Depends(get_db),
                me: User = Depends(operational_user)):
    resident = _my_resident(db, me)
    # "Saya Aman" = laporan mandiri, tidak pernah langsung aman terverifikasi (PRD §9.2)
    new_status = SafetyStatus.AMAN_MANDIRI if body.status == "aman" else SafetyStatus.BUTUH_BANTUAN
    now = utcnow()
    share = body.lat is not None
    if share and not resident.location_consented:
        resident.location_consent_at, resident.location_consent_version = now, CONSENT_VERSION
        resident.location_revoked_at = None
    log = ResidentStatusLog(
        resident_id=resident.id, incident_id=_resolve_incident(db, body.incident_id, resident.region_id),
        status=new_status, source=StatusSource.MANDIRI, need_type=body.need_type, note=body.note,
        lat=body.lat if share else None, lng=body.lng if share else None, updated_by=me.id, created_at=now,
    )
    if share:
        resident.last_lat, resident.last_lng, resident.last_location_at = body.lat, body.lng, now
    db.add(log)
    db.flush()
    alert = None
    if new_status == SafetyStatus.BUTUH_BANTUAN:
        region = db.get(Region, resident.region_id)
        need = body.need_type.value if body.need_type else "bantuan"
        nl = chr(10)
        alert = emit(
            db, kind=AlertKind.BANTUAN, internal=True, audience_region_id=resident.region_id, now=now,
            target_roles=["koordinator", "tim_sar"], dedupe_key=f"bantuan:{resident.id}", dedupe_minutes=10,
            message=(f"[RIKSA WARGA — WARGA BUTUH BANTUAN]{nl}Wilayah: {region.name if region else '-'}{nl}"
                     f"Jenis: {need}{nl}Buka aplikasi untuk detail, prioritas, dan peta."))
    log_action(db, actor_id=me.id, action="resident.self_status", entity_type="resident", entity_id=resident.id,
               new={"status": new_status.value, "incident_id": log.incident_id, "lokasi": share})
    db.commit()
    notifier.schedule(background, db, [alert])
    return log


@router.post("/me/location", response_model=ResidentDetail)
def share_location(body: LocationIn, db: Session = Depends(get_db), me: User = Depends(operational_user)):
    """Lokasi terkini / lokasi rumah warga. Butuh izin sekali; hanya dipakai pihak lain saat Mode Bencana."""
    resident = _my_resident(db, me)
    if not resident.location_consented:
        resident.location_consent_at, resident.location_consent_version = utcnow(), CONSENT_VERSION
        resident.location_revoked_at = None
    if body.kind == "rumah":
        resident.home_lat, resident.home_lng = body.lat, body.lng
    else:
        resident.last_lat, resident.last_lng, resident.last_location_at = body.lat, body.lng, utcnow()
    # koordinat tidak disalin ke audit log, cukup jenisnya
    log_action(db, actor_id=me.id, action="resident.location", entity_type="resident", entity_id=resident.id,
               new={"kind": body.kind})
    db.commit()
    return _own_view(db, resident)
