"""Permintaan bantuan & tugas Tim SAR (PRD §7.5, FR-060–066).

Koordinator mengajukan bantuan (tugas) dengan prioritas; Tim SAR menerima/menolak, menuju lokasi, menangani,
lalu membuat laporan pasca-bantuan. Status warga mengikuti tugas.
"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import (
    city_scope_ids,
    ensure_region_access,
    operational_user,
    require_role,
    user_scope_ids,
)
from app.db import get_db, utcnow
from app.models import (
    AlertKind,
    Incident,
    NeedType,
    Region,
    RescueReport,
    RescueTask,
    Resident,
    ResidentStatusLog,
    Role,
    SafetyStatus,
    Shelter,
    ShelterCheckin,
    StatusSource,
    TaskStatus,
    TaskType,
    User,
)
from app.schemas import (
    RescueReportIn,
    RescueReportOut,
    TaskAssignIn,
    TaskCreate,
    TaskOut,
    TaskRejectIn,
    TaskUpdateIn,
    UserOut,
)
from app.services import engine, notifier
from app.services.alerting import emit
from app.services.disaster import last_location_usable, mode_regions
from app.services.evacuation import resident_location
from app.services.messages import fmt_time

router = APIRouter(prefix="/tasks", tags=["tugas tim sar"])
coordinator = require_role(Role.KOORDINATOR)
sar_only = require_role(Role.TIM_SAR)

FINAL = {TaskStatus.SELESAI, TaskStatus.GAGAL, TaskStatus.DIBATALKAN}
NEXT = {
    TaskStatus.BARU: {TaskStatus.DIBATALKAN},
    TaskStatus.MENUNGGU: {TaskStatus.DITERIMA, TaskStatus.GAGAL, TaskStatus.DIBATALKAN},
    TaskStatus.DITERIMA: {TaskStatus.MENUJU, TaskStatus.GAGAL, TaskStatus.DIBATALKAN},
    TaskStatus.MENUJU: {TaskStatus.DITANGANI, TaskStatus.GAGAL, TaskStatus.DIBATALKAN},
    TaskStatus.DITANGANI: {TaskStatus.SELESAI, TaskStatus.GAGAL, TaskStatus.DIBATALKAN},
}
TASK_NEED = {TaskType.EVAKUASI: NeedType.EVAKUASI, TaskType.MEDIS: NeedType.MEDIS, TaskType.LOGISTIK: NeedType.LOGISTIK}


def _view(db: Session, t: RescueTask) -> dict:
    out = TaskOut.model_validate(t).model_dump()
    if t.resident_id:
        r = db.get(Resident, t.resident_id)
        # Tim SAR hanya mendapat data yang perlu untuk tugas: nama + kategori kerentanan, bukan catatan sensitif
        out["resident_name"], out["resident_vulnerability"] = r.name, list(r.vulnerability or [])
    if t.assignee_id:
        out["assignee_name"] = db.get(User, t.assignee_id).name
    return out


def _open_for_sar(task: RescueTask) -> bool:
    return task.assignee_id is None and task.status == TaskStatus.BARU


def _get(db: Session, me: User, task_id: int) -> RescueTask:
    task = db.get(RescueTask, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tugas tidak ditemukan")
    if me.role == Role.TIM_SAR:
        if task.assignee_id != me.id and not _open_for_sar(task):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Bukan tugas Anda")
    elif me.role == Role.KOORDINATOR:
        ensure_region_access(db, me, task.region_id)
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Peran tidak diizinkan")
    return task


def _check_assignee(db: Session, assignee_id: int) -> User:
    user = db.get(User, assignee_id)
    if user is None or not user.is_active or user.role != Role.TIM_SAR:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Penerima tugas harus anggota Tim SAR aktif")
    return user


def _announce_request(db: Session, task: RescueTask, region_id: int):
    """Notifikasi Tim SAR (aplikasi, Telegram, SMS). Tanpa nama/lokasi warga: detail hanya di aplikasi (PRD §7.3)."""
    region = db.get(Region, region_id)
    text = chr(10).join([
        f"[RIKSA WARGA — PERMINTAAN BANTUAN #{task.id}]",
        f"Wilayah: {region.name if region else '-'}",
        f"Jenis: {task.task_type.value} · Prioritas: {task.priority.value.upper()}",
        f"Waktu: {fmt_time(task.created_at)}",
        "Tindakan: buka aplikasi Riksa Warga untuk detail, peta, dan rute. Terima atau tolak tugas.",
    ])
    return emit(db, kind=AlertKind.TUGAS, internal=True, audience_region_id=region_id, message=text,
                created_by=task.created_by, sms=True, target_roles=["tim_sar"], now=task.created_at)


def _resident_status(db: Session, task: RescueTask, me: User, new: SafetyStatus, note: str,
                     need: NeedType | None = None) -> None:
    if task.resident_id is None:
        return
    db.add(ResidentStatusLog(resident_id=task.resident_id, incident_id=task.incident_id, status=new,
                             source=StatusSource.PETUGAS, need_type=need, note=note, updated_by=me.id,
                             created_at=utcnow()))


@router.get("/teams", response_model=list[UserOut])
def sar_teams(db: Session = Depends(get_db), me: User = Depends(coordinator)):
    """Daftar anggota Tim SAR se-kota untuk dipilih koordinator."""
    return db.scalars(select(User).where(User.role == Role.TIM_SAR, User.is_active.is_(True),
                                         User.region_id.in_(city_scope_ids(db, me.region_id))).order_by(User.name)).all()


@router.get("", response_model=list[TaskOut])
def list_tasks(status_: TaskStatus | None = Query(None, alias="status"), active: bool = False,
               db: Session = Depends(get_db), me: User = Depends(operational_user)):
    q = select(RescueTask).order_by(RescueTask.id.desc())
    if me.role == Role.TIM_SAR:
        # tugas sendiri + permintaan yang belum diambil siapa pun (se-kota)
        q = q.where((RescueTask.assignee_id == me.id) | (
            RescueTask.assignee_id.is_(None) & (RescueTask.status == TaskStatus.BARU)))
    elif me.role == Role.KOORDINATOR:
        scope = user_scope_ids(db, me)
        if scope is not None:
            q = q.where(RescueTask.region_id.in_(scope))
    elif me.role == Role.POS_PANTAU:
        scope = city_scope_ids(db, me.region_id)
        if scope is not None:
            q = q.where(RescueTask.region_id.in_(scope))
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Peran tidak diizinkan")
    if status_:
        q = q.where(RescueTask.status == status_)
    if active:
        q = q.where(RescueTask.status.not_in(FINAL))
    return [_view(db, t) for t in db.scalars(q)]


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db), me: User = Depends(operational_user)):
    return _view(db, _get(db, me, task_id))


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(body: TaskCreate, background: BackgroundTasks, db: Session = Depends(get_db),
                me: User = Depends(coordinator)):
    """Koordinator mengajukan bantuan ke Tim SAR (FR-062). Tanpa penerima = permintaan terbuka untuk semua Tim SAR."""
    resident = db.get(Resident, body.resident_id) if body.resident_id else None
    if body.resident_id and resident is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Warga tidak ditemukan")
    region_id = body.region_id or (resident.region_id if resident else None)
    if region_id is None or db.get(Region, region_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Wilayah tugas wajib diisi")
    ensure_region_access(db, me, region_id)
    if resident:
        ensure_region_access(db, me, resident.region_id)
    if body.incident_id and db.get(Incident, body.incident_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Kejadian tidak ditemukan")
    if body.shelter_id and db.get(Shelter, body.shelter_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Shelter tidak ditemukan")
    now = utcnow()
    lat, lng = body.lat, body.lng
    if lat is None and resident:
        # lokasi terkini hanya dipakai saat Mode Bencana + izin warga; selain itu lokasi rumah
        allow = last_location_usable(resident, mode_regions(db, now), now)
        loc = resident_location(resident, now, allow)
        if loc:
            lat, lng = loc[0], loc[1]
    assignee = _check_assignee(db, body.assignee_id) if body.assignee_id else None
    task = RescueTask(
        incident_id=body.incident_id, resident_id=body.resident_id, region_id=region_id, task_type=body.task_type,
        priority=body.priority, description=body.description, lat=lat, lng=lng,
        assignee_id=assignee.id if assignee else None, shelter_id=body.shelter_id,
        status=TaskStatus.MENUNGGU if assignee else TaskStatus.BARU, created_by=me.id, created_at=now, updated_at=now)
    db.add(task)
    db.flush()
    log_action(db, actor_id=me.id, action="task.create", entity_type="task", entity_id=task.id,
               new={"type": task.task_type.value, "priority": task.priority.value, "assignee_id": task.assignee_id,
                    "resident_id": task.resident_id})
    alert = _announce_request(db, task, region_id)
    db.commit()
    notifier.schedule(background, db, [alert])
    return _view(db, task)


@router.post("/{task_id}/assign", response_model=TaskOut)
def assign_task(task_id: int, body: TaskAssignIn, background: BackgroundTasks, db: Session = Depends(get_db),
                me: User = Depends(coordinator)):
    task = _get(db, me, task_id)
    if task.status not in (TaskStatus.BARU, TaskStatus.MENUNGGU, TaskStatus.DITERIMA):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Tugas {task.status.value} tidak bisa ditugaskan ulang")
    assignee = _check_assignee(db, body.assignee_id)
    old = task.assignee_id
    task.assignee_id, task.status, task.updated_at = assignee.id, TaskStatus.MENUNGGU, utcnow()
    log_action(db, actor_id=me.id, action="task.assign", entity_type="task", entity_id=task.id,
               old={"assignee_id": old}, new={"assignee_id": assignee.id})
    alert = _announce_request(db, task, task.region_id)
    db.commit()
    notifier.schedule(background, db, [alert])
    return _view(db, task)


@router.post("/{task_id}/claim", response_model=TaskOut)
@engine.locked
def claim_task(task_id: int, db: Session = Depends(get_db), me: User = Depends(sar_only)):
    """Tim SAR mengambil permintaan terbuka. Dikunci agar dua tim tidak mengambil tugas yang sama."""
    task = _get(db, me, task_id)
    if not _open_for_sar(task):
        raise HTTPException(status.HTTP_409_CONFLICT, "Permintaan sudah diambil tim lain")
    task.assignee_id, task.status, task.updated_at = me.id, TaskStatus.DITERIMA, utcnow()
    _resident_status(db, task, me, SafetyStatus.DALAM_PENANGANAN, f"Tugas #{task.id} diambil {me.name}")
    log_action(db, actor_id=me.id, action="task.claim", entity_type="task", entity_id=task.id,
               new={"assignee_id": me.id})
    db.commit()
    return _view(db, task)


@router.post("/{task_id}/reject", response_model=TaskOut)
def reject_task(task_id: int, body: TaskRejectIn, db: Session = Depends(get_db), me: User = Depends(sar_only)):
    """Tim SAR menolak tugas yang ditujukan kepadanya; kembali ke antrean terbuka dengan alasan tercatat."""
    task = _get(db, me, task_id)
    if task.assignee_id != me.id or task.status != TaskStatus.MENUNGGU:
        raise HTTPException(status.HTTP_409_CONFLICT, "Hanya tugas yang menunggu penerimaan Anda yang bisa ditolak")
    task.assignee_id, task.status, task.updated_at = None, TaskStatus.BARU, utcnow()
    log_action(db, actor_id=me.id, action="task.reject", entity_type="task", entity_id=task.id,
               old={"assignee_id": me.id}, new={"status": TaskStatus.BARU.value}, reason=body.reason)
    db.commit()
    return _view(db, task)


@router.post("/{task_id}/status", response_model=TaskOut)
def update_task(task_id: int, body: TaskUpdateIn, db: Session = Depends(get_db),
                me: User = Depends(operational_user)):
    task = _get(db, me, task_id)
    if me.role == Role.TIM_SAR and task.assignee_id != me.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Bukan tugas Anda")
    new = body.status
    if new not in NEXT.get(task.status, set()):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Tidak bisa dari '{task.status.value}' ke '{new.value}'")
    if new == TaskStatus.DIBATALKAN and me.role == Role.TIM_SAR:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Pembatalan hanya oleh koordinator")
    if new in FINAL and not (body.note and len(body.note.strip()) >= 3):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Catat hasil / alasan (min. 3 karakter)")
    if body.shelter_id and db.get(Shelter, body.shelter_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Shelter tidak ditemukan")
    shelter_id = body.shelter_id or task.shelter_id

    old = task.status
    task.status, task.updated_at, task.shelter_id = new, utcnow(), shelter_id
    if body.people_count is not None:
        task.people_count = body.people_count
    if new in FINAL:
        task.result = body.note
    who = f"Tugas #{task.id} ({me.name})"
    if new == TaskStatus.DITERIMA:
        _resident_status(db, task, me, SafetyStatus.DALAM_PENANGANAN, f"{who} diterima")
    elif new == TaskStatus.SELESAI and shelter_id:
        shelter = db.get(Shelter, shelter_id)
        _resident_status(db, task, me, SafetyStatus.TIBA_DI_TITIK_AMAN, f"{who}: tiba di {shelter.name}. {body.note}")
        name = db.get(Resident, task.resident_id).name if task.resident_id else f"Tugas #{task.id}"
        db.add(ShelterCheckin(shelter_id=shelter_id, resident_id=task.resident_id, name=name,
                              people_count=task.people_count or 1, task_id=task.id, checked_by=me.id,
                              created_at=utcnow()))
    elif new == TaskStatus.GAGAL:
        # kembali ke antrean agar koordinator menugaskan ulang
        _resident_status(db, task, me, SafetyStatus.BUTUH_BANTUAN, f"{who} gagal: {body.note}",
                         TASK_NEED.get(task.task_type, NeedType.LAINNYA))
    log_action(db, actor_id=me.id, action="task.status", entity_type="task", entity_id=task.id,
               old={"status": old.value}, new={"status": new.value, "shelter_id": shelter_id}, reason=body.note)
    db.commit()
    return _view(db, task)


@router.post("/{task_id}/report", response_model=RescueReportOut, status_code=status.HTTP_201_CREATED)
def create_rescue_report(task_id: int, body: RescueReportIn, db: Session = Depends(get_db),
                         me: User = Depends(sar_only)):
    """Laporan pasca-bantuan (FR-065): satu per tugas, terhubung ke tugas, tersimpan permanen."""
    task = _get(db, me, task_id)
    if task.assignee_id != me.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Bukan tugas Anda")
    if task.status not in (TaskStatus.SELESAI, TaskStatus.GAGAL):
        raise HTTPException(status.HTTP_409_CONFLICT, "Laporan dibuat setelah tugas selesai atau gagal")
    if db.scalar(select(RescueReport.id).where(RescueReport.task_id == task.id)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tugas ini sudah memiliki laporan")
    report = RescueReport(task_id=task.id, reported_by=me.id, created_at=utcnow(), **body.model_dump())
    db.add(report)
    db.flush()
    log_action(db, actor_id=me.id, action="rescue.report", entity_type="task", entity_id=task.id,
               new={"orang": body.people_helped, "kondisi": body.condition})
    db.commit()
    return report


@router.get("/{task_id}/report", response_model=RescueReportOut | None)
def get_rescue_report(task_id: int, db: Session = Depends(get_db), me: User = Depends(operational_user)):
    _get(db, me, task_id)
    return db.scalar(select(RescueReport).where(RescueReport.task_id == task_id))
