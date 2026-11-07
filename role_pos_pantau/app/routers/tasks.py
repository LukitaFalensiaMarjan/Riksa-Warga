"""Penugasan Tim SAR (PRD v2 §7.5) dengan alur status PRD v1 §12.3 + laporan pasca-bantuan."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import ensure_region_access, get_current_user, require_role, user_scope_ids
from app.db import get_db, utcnow
from app.models import (
    Incident,
    NeedType,
    Region,
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
from app.schemas import TaskAssignIn, TaskCreate, TaskOut, TaskUpdateIn
from app.services import notifier
from app.services.evacuation import resident_location

from typing import Literal

from pydantic import BaseModel, Field

from app.models import RescueReport

router = APIRouter(prefix="/tasks", tags=["tugas tim sar"])
coordinator = require_role(Role.KOORDINATOR)
FIELD_ROLES = (Role.TIM_SAR,)

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
        # relawan hanya mendapat data yang perlu untuk tugas: nama + kategori kerentanan, bukan catatan sensitif
        out["resident_name"], out["resident_vulnerability"] = r.name, list(r.vulnerability or [])
    if t.assignee_id:
        out["assignee_name"] = db.get(User, t.assignee_id).name
    return out


def _get(db: Session, me: User, task_id: int) -> RescueTask:
    task = db.get(RescueTask, task_id)
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tugas tidak ditemukan")
    if me.role in FIELD_ROLES:
        if task.assignee_id != me.id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Bukan tugas Anda")
    elif me.role == Role.KOORDINATOR:
        ensure_region_access(db, me, task.region_id)
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Peran tidak diizinkan")
    return task


def _check_assignee(db: Session, assignee_id: int) -> User:
    user = db.get(User, assignee_id)
    if user is None or not user.is_active or user.role not in FIELD_ROLES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Penerima tugas harus relawan/petugas aktif")
    return user


def _notify(background: BackgroundTasks, user: User, task: RescueTask) -> None:
    # tanpa nama/lokasi warga: detail hanya di aplikasi (PRD §18.1)
    text = (f"[RIKSA WARGA — TUGAS BARU #{task.id}]\nJenis: {task.task_type.value} · Prioritas: "
            f"{task.priority.value.upper()}\nBuka aplikasi Riksa Warga untuk detail & rute.")
    if user.telegram_chat_id:
        background.add_task(notifier.send_telegram, user.telegram_chat_id, text)
    if user.phone:  # PRD v2: tugas baru juga lewat SMS
        background.add_task(notifier.send_sms, user.phone, text)


def _resident_status(db: Session, task: RescueTask, me: User, new: SafetyStatus, note: str,
                     need: NeedType | None = None) -> None:
    if task.resident_id is None:
        return
    db.add(ResidentStatusLog(resident_id=task.resident_id, incident_id=task.incident_id, status=new,
                             source=StatusSource.TIM_SAR, need_type=need, note=note, updated_by=me.id,
                             created_at=utcnow()))


@router.get("", response_model=list[TaskOut])
def list_tasks(status_: TaskStatus | None = Query(None, alias="status"), active: bool = False,
               db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    q = select(RescueTask).order_by(RescueTask.id.desc())
    if me.role in FIELD_ROLES:
        q = q.where(RescueTask.assignee_id == me.id)  # FR-071: relawan hanya tugasnya
    elif me.role == Role.KOORDINATOR:
        scope = user_scope_ids(db, me)
        if scope is not None:
            q = q.where(RescueTask.region_id.in_(scope))
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Peran tidak diizinkan")
    if status_:
        q = q.where(RescueTask.status == status_)
    if active:
        q = q.where(RescueTask.status.not_in(FINAL))
    return [_view(db, t) for t in db.scalars(q)]


@router.get("/assignees")
def assignees(db: Session = Depends(get_db), me: User = Depends(coordinator)):
    """Daftar Tim SAR aktif untuk penugasan (koordinator tidak boleh membaca daftar akun penuh)."""
    rows = db.scalars(select(User).where(User.role == Role.TIM_SAR, User.is_active.is_(True)).order_by(User.name))
    return [{"id": u.id, "name": u.name} for u in rows]


@router.get("/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    return _view(db, _get(db, me, task_id))


@router.post("", response_model=TaskOut, status_code=status.HTTP_201_CREATED)
def create_task(body: TaskCreate, background: BackgroundTasks, db: Session = Depends(get_db),
                me: User = Depends(coordinator)):
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
    lat, lng = body.lat, body.lng
    if lat is None and resident and (loc := resident_location(resident, utcnow())):
        lat, lng = loc[0], loc[1]
    assignee = _check_assignee(db, body.assignee_id) if body.assignee_id else None
    now = utcnow()
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
    db.commit()
    if assignee:
        _notify(background, assignee, task)
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
    db.commit()
    _notify(background, assignee, task)
    return _view(db, task)


@router.post("/{task_id}/status", response_model=TaskOut)
def update_task(task_id: int, body: TaskUpdateIn, db: Session = Depends(get_db),
                me: User = Depends(get_current_user)):
    task = _get(db, me, task_id)
    new = body.status
    if new not in NEXT.get(task.status, set()):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Tidak bisa dari '{task.status.value}' ke '{new.value}'")
    if new == TaskStatus.DIBATALKAN and me.role in FIELD_ROLES:
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


# ---------- Laporan pasca-bantuan Tim SAR (FR-065) ----------

class RescueReportIn(BaseModel):
    people_helped: int = Field(ge=0, le=500)
    condition: Literal["selamat", "luka", "butuh_rujukan", "lainnya"]
    destination: str | None = Field(default=None, max_length=160)  # shelter / RS / lainnya
    obstacles: str | None = Field(default=None, max_length=1000)
    notes: str | None = Field(default=None, max_length=2000)


def _report_view(r: RescueReport) -> dict:
    return {"id": r.id, "task_id": r.task_id, "people_helped": r.people_helped, "condition": r.condition,
            "destination": r.destination, "obstacles": r.obstacles, "notes": r.notes, "created_by": r.created_by,
            "created_at": r.created_at}


@router.post("/{task_id}/report", status_code=status.HTTP_201_CREATED)
def create_rescue_report(task_id: int, body: RescueReportIn, db: Session = Depends(get_db),
                         me: User = Depends(require_role(Role.TIM_SAR))):
    """Hanya Tim SAR yang ditugaskan, setelah tugas berjalan/selesai/gagal."""
    task = _get(db, me, task_id)
    if task.assignee_id != me.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Bukan tugas Anda")
    if task.status not in (TaskStatus.DITANGANI, TaskStatus.SELESAI, TaskStatus.GAGAL):
        raise HTTPException(status.HTTP_409_CONFLICT, "Laporan dibuat setelah penanganan dimulai/selesai")
    row = RescueReport(task_id=task.id, created_by=me.id, created_at=utcnow(), **body.model_dump())
    db.add(row)
    db.flush()
    log_action(db, actor_id=me.id, action="task.report", entity_type="task", entity_id=task.id,
               new={"people_helped": body.people_helped, "condition": body.condition})
    db.commit()
    return _report_view(row)


@router.get("/{task_id}/reports")
def list_rescue_reports(task_id: int, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    task = _get(db, me, task_id)  # SAR: tugasnya; koordinator: wilayahnya
    rows = db.scalars(select(RescueReport).where(RescueReport.task_id == task.id).order_by(RescueReport.id)).all()
    return [_report_view(r) for r in rows]
