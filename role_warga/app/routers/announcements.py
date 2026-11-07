"""Pengumuman pos pantau ke semua role non-admin lewat aplikasi, Telegram, dan SMS (PRD v2 §7.2, FR-028/029)."""
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import OPERATOR_ROLES, ensure_region_access, require_role
from app.db import get_db, utcnow
from app.models import Alert, AlertKind, Region, Report, ReportStatus, User
from app.schemas import AlertOut
from app.services import announce, bulletin, engine, notifier

router = APIRouter(prefix="/announcements", tags=["pengumuman"])
operator = require_role(*OPERATOR_ROLES)


class AnnouncementIn(BaseModel):
    severity: Literal["informasi", "waspada", "meluap"]
    region_id: int
    summary: str = Field(min_length=5, max_length=500)
    report_id: int | None = None  # dasar: laporan warga yang SUDAH diverifikasi
    basis_note: str | None = Field(default=None, max_length=300)  # atau pengamatan langsung (alasan tercatat)
    source_mode: Literal["real", "simulation"] = "real"


class CorrectionIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)
    message: str | None = Field(default=None, max_length=500)


class BulletinIn(BaseModel):
    note: str | None = Field(default=None, max_length=300)  # catatan tambahan pos pantau (opsional)


@router.get("/bulletin")
def bulletin_preview(db: Session = Depends(get_db), me: User = Depends(operator)):
    """Ringkasan live monitoring semua pos + peringatan dini + pratinjau pesan Telegram."""
    return bulletin.build(db, utcnow())


@router.post("/bulletin", response_model=AlertOut, status_code=status.HTTP_201_CREATED)
@engine.locked
def bulletin_send(body: BulletinIn, background: BackgroundTasks, db: Session = Depends(get_db),
                  me: User = Depends(operator)):
    """Siarkan buletin (data saat tombol ditekan) ke aplikasi + Telegram; SMS hanya bila waspada/meluap."""
    now = utcnow()
    note = body.note.strip() if body.note and body.note.strip() else None
    b = bulletin.build(db, now, note)
    alert = announce._add(db, AlertKind.PENGUMUMAN, b["message"], audience=announce.kelurahan_of(db, me.region_id),
                          now=now, sms=b["severity"] != "informasi", severity=b["severity"], actor_id=me.id)
    log_action(db, actor_id=me.id, action="announcement.bulletin", entity_type="alert", entity_id=alert.id,
               new={"severity": b["severity"], "counts": b["counts"]})
    db.commit()
    notifier.schedule(background, db, [alert])
    return alert


@router.post("", response_model=AlertOut, status_code=status.HTTP_201_CREATED)
@engine.locked
def create_announcement(body: AnnouncementIn, background: BackgroundTasks, db: Session = Depends(get_db),
                        me: User = Depends(operator)):
    region = db.get(Region, body.region_id)
    if region is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Wilayah tidak ditemukan")
    ensure_region_access(db, me, region.id)
    if body.report_id is not None:
        report = db.get(Report, body.report_id)
        if report is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Laporan tidak ditemukan")
        ensure_region_access(db, me, report.region_id)
        if report.status != ReportStatus.TERVERIFIKASI:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                                "Pengumuman berdasar laporan wajib memakai laporan yang sudah diverifikasi")
        basis = f"laporan warga terverifikasi #{report.id}, dicocokkan dengan data sungai dan hujan"
    elif body.basis_note:
        basis = f"pengamatan langsung pos pantau — {body.basis_note}"
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            "Sertakan report_id (laporan terverifikasi) atau basis_note (pengamatan langsung)")
    now = utcnow()
    alert = announce.announcement(db, severity=body.severity, region_id=region.id, area=region.name,
                                  summary=body.summary, basis=basis, simulation=body.source_mode == "simulation",
                                  actor_id=me.id, now=now)
    log_action(db, actor_id=me.id, action="announcement.create", entity_type="alert", entity_id=alert.id,
               new={"severity": body.severity, "region_id": region.id, "report_id": body.report_id})
    db.commit()
    notifier.schedule(background, db, [alert])
    return alert


@router.post("/{alert_id}/correct", response_model=AlertOut, status_code=status.HTTP_201_CREATED)
@engine.locked
def correct_announcement(alert_id: int, body: CorrectionIn, background: BackgroundTasks,
                         db: Session = Depends(get_db), me: User = Depends(operator)):
    parent = db.get(Alert, alert_id)
    if parent is None or parent.kind != AlertKind.PENGUMUMAN:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pengumuman tidak ditemukan")
    ensure_region_access(db, me, parent.audience_region_id)
    alert = announce.correction(db, parent, body.reason, body.message, me.id, utcnow())
    log_action(db, actor_id=me.id, action="announcement.correct", entity_type="alert", entity_id=parent.id,
               new={"koreksi_id": alert.id}, reason=body.reason)
    db.commit()
    notifier.schedule(background, db, [alert])
    return alert
