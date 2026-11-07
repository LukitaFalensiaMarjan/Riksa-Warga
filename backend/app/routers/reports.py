import hashlib
import uuid
from datetime import timedelta
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import can_access_region, city_scope_ids, ensure_city_access, ensure_region_access, operational_user, require_role, user_scope_ids
from app.config import settings
from app.db import get_db, to_utc_naive, utcnow
from app.models import AlertKind, Hazard, Incident, Region, Report, ReportSource, ReportStatus, Role, User
from app.schemas import NoteIn, ReasonIn, ReportCreate, ReportMineOut, ReportOut
from app.services import engine, notifier
from app.services.alerting import emit
from app.services.matching import match_report

router = APIRouter(prefix="/reports", tags=["laporan"])
coordinator = require_role(Role.KOORDINATOR, Role.POS_PANTAU, Role.ADMIN)
reporter = operational_user

FUTURE_TOLERANCE = timedelta(minutes=5)


def _detect_image(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return None


def _source_for(user: User, from_sensor: bool) -> ReportSource:
    if from_sensor:
        if user.role != Role.POS_PANTAU:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Hanya pos pantau yang dapat mengirim indikasi sensor")
        return ReportSource.SENSOR
    return {Role.POS_PANTAU: ReportSource.POS_PANTAU,
            Role.KOORDINATOR: ReportSource.KOORDINATOR}.get(user.role, ReportSource.WARGA)


def _get_report(db: Session, report_id: int) -> Report:
    report = db.get(Report, report_id)
    if report is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Laporan tidak ditemukan")
    return report


def _readable(db: Session, me: User, report: Report) -> Report:
    if report.reporter_id != me.id and not (
            me.role in (Role.KOORDINATOR, Role.POS_PANTAU, Role.TIM_SAR, Role.RELAWAN, Role.ADMIN)
            and can_access_region(db, me, report.region_id)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tidak berhak melihat laporan ini")
    return report


@router.post("", response_model=ReportMineOut, status_code=status.HTTP_201_CREATED)
@engine.locked
def create_report(body: ReportCreate, background: BackgroundTasks, db: Session = Depends(get_db),
                  me: User = Depends(reporter)):
    if body.client_ref:  # kirim ulang dari antrean offline -> kembalikan laporan yang sama, bukan duplikat
        existing = db.scalar(select(Report).where(Report.reporter_id == me.id, Report.client_ref == body.client_ref))
        if existing is not None:
            return existing
    now = utcnow()
    recent = db.scalar(select(func.count(Report.id)).where(
        Report.reporter_id == me.id, Report.received_at >= now - timedelta(minutes=10)))
    if recent >= settings.report_rate_limit_per_10min:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Terlalu banyak laporan, coba lagi beberapa menit")

    region_id = body.region_id
    if db.get(Region, region_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Wilayah tidak ditemukan")
    reported_at = to_utc_naive(body.reported_at) if body.reported_at else now
    if reported_at > now + FUTURE_TOLERANCE:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Waktu kejadian tidak boleh di masa depan")

    report = Report(
        title=body.title, location_name=body.location_name, conditions=body.conditions or [],
        reporter_id=me.id, region_id=region_id, hazard=body.hazard, fire_indicator=body.fire_indicator,
        source=_source_for(me, body.from_sensor), source_mode=body.source_mode, description=body.description,
        lat=body.lat, lng=body.lng, gps_lat=body.gps_lat, gps_lng=body.gps_lng, reported_at=reported_at,
        received_at=now, status=ReportStatus.DITERIMA, flags=[], score_factors=[], client_ref=body.client_ref,
    )
    db.add(report)
    db.flush()
    if report.hazard == Hazard.LAINNYA:
        # jenis lain: hanya diteruskan ke pos pantau sebagai informasi, tanpa mesin aturan (PRD §4.4)
        region = db.get(Region, report.region_id)
        nl = chr(10)
        alerts = [emit(db, kind=AlertKind.PANTAU, internal=True, audience_region_id=report.region_id, now=now,
                       target_roles=["pos_pantau"],
                       message=("[RIKSA WARGA — LAPORAN LAIN (INFORMASI)]" + nl + "Wilayah: " + (region.name if region else "-")
                                + nl + report.description[:200] + nl + "Buka aplikasi untuk detail."))]
    else:
        alerts = engine.process_new_report(db, report, now)
    log_action(db, actor_id=me.id, action="report.create", entity_type="report", entity_id=report.id,
               new={"hazard": report.hazard.value, "incident_id": report.incident_id,
                    "status": report.status.value, "source_mode": report.source_mode.value})
    db.commit()
    notifier.schedule(background, db, alerts)
    return report


@router.get("/mine", response_model=list[ReportMineOut])
def my_reports(db: Session = Depends(get_db), me: User = Depends(operational_user)):
    return db.scalars(select(Report).where(Report.reporter_id == me.id).order_by(Report.id.desc())).all()


@router.get("", response_model=list[ReportOut])
def list_reports(
    status_: ReportStatus | None = Query(None, alias="status"),
    hazard: Hazard | None = None,
    incident_id: int | None = None,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    me: User = Depends(coordinator),
):
    q = select(Report).order_by(Report.id.desc()).limit(limit)
    if me.role == Role.KOORDINATOR:
        scope = user_scope_ids(db, me)
        if scope is not None:
            q = q.where(Report.region_id.in_(scope))
    elif me.role == Role.POS_PANTAU:
        scope = city_scope_ids(db, me.region_id)
        if scope is not None:
            q = q.where(Report.region_id.in_(scope))
    if status_:
        q = q.where(Report.status == status_)
    if hazard:
        q = q.where(Report.hazard == hazard)
    if incident_id:
        q = q.where(Report.incident_id == incident_id)
    return db.scalars(q).all()


@router.get("/{report_id}/match")
def report_match(report_id: int, db: Session = Depends(get_db), me: User = Depends(coordinator)):
    """Panel pencocokan laporan vs sungai, hujan, pelapor lain (FR-025). Pos pantau hanya di wilayah tugasnya."""
    report = _get_report(db, report_id)
    if me.role == Role.KOORDINATOR:
        ensure_region_access(db, me, report.region_id)
    else:
        ensure_city_access(db, me, report.region_id)
    return match_report(db, report, utcnow())


@router.get("/{report_id}", response_model=ReportOut)
def get_report(report_id: int, db: Session = Depends(get_db), me: User = Depends(operational_user)):
    return _readable(db, me, _get_report(db, report_id))


@router.post("/{report_id}/photo", response_model=ReportMineOut)
@engine.locked
def upload_photo(report_id: int, background: BackgroundTasks, file: UploadFile = File(...),
                 db: Session = Depends(get_db), me: User = Depends(operational_user)):
    report = _get_report(db, report_id)
    if report.reporter_id != me.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Hanya pelapor yang dapat melampirkan foto")
    if report.photo_path:
        raise HTTPException(status.HTTP_409_CONFLICT, "Laporan sudah memiliki foto")

    limit = settings.max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                            f"Ukuran foto maksimal {settings.max_upload_mb} MB")
    ext = _detect_image(data)  # cek isi file, bukan nama/Content-Type dari klien
    if ext is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Foto harus JPG, PNG, atau WebP")

    sha = hashlib.sha256(data).hexdigest()
    name = f"{uuid.uuid4().hex}.{ext}"
    folder = Path(settings.upload_dir)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(data)

    report.photo_path, report.photo_sha256 = name, sha
    reused = db.scalar(select(Report.id).where(Report.photo_sha256 == sha, Report.id != report.id).limit(1))
    if reused:
        report.flags = [*report.flags, "foto_pernah_dipakai"]
    db.flush()
    now = utcnow()
    incident = db.get(Incident, report.incident_id) if report.incident_id else None
    alerts = engine.evaluate_incident(db, incident, now) if incident else []
    log_action(db, actor_id=me.id, action="report.photo", entity_type="report", entity_id=report.id,
               new={"sha256": sha, "foto_sama_dengan_laporan": reused})
    db.commit()
    notifier.schedule(background, db, alerts)
    return report


@router.get("/{report_id}/photo")
def get_photo(report_id: int, db: Session = Depends(get_db), me: User = Depends(operational_user)):
    report = _readable(db, me, _get_report(db, report_id))
    if not report.photo_path:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Laporan tidak memiliki foto")
    return FileResponse(Path(settings.upload_dir) / report.photo_path)


def _review(db: Session, me: User, report_id: int, new_status: ReportStatus, reason: str | None,
            background: BackgroundTasks, condition: str | None = None) -> Report:
    report = _get_report(db, report_id)
    if me.role == Role.KOORDINATOR:
        ensure_region_access(db, me, report.region_id)
    else:
        ensure_city_access(db, me, report.region_id)
    if report.status in (ReportStatus.TERVERIFIKASI, ReportStatus.DITOLAK):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Laporan sudah {report.status.value}")
    now = utcnow()
    old = report.status
    report.status, report.status_reason = new_status, reason
    report.reviewed_by, report.reviewed_at = me.id, now
    db.flush()
    action = "report.verify" if new_status == ReportStatus.TERVERIFIKASI else "report.reject"
    log_action(db, actor_id=me.id, action=action, entity_type="report", entity_id=report.id,
               old={"status": old.value}, new={"status": new_status.value, "condition": condition}, reason=reason)
    incident = db.get(Incident, report.incident_id) if report.incident_id else None
    alerts = engine.evaluate_incident(db, incident, now) if incident else []

    # Jika pos pantau menerima laporan dan menetapkan kondisi waspada atau meluap:
    if new_status == ReportStatus.TERVERIFIKASI and condition in ("waspada", "meluap"):
        from app.services.alerting import emit
        cond_label = condition.upper()
        alert_lvl = AlertLevel.WASPADA if condition == "waspada" else AlertLevel.EVAKUASI
        if incident:
            incident.level = alert_lvl
            incident.verification = Verification.TERVERIFIKASI
            db.flush()

        loc_str = getattr(report, "location_name", None) or report.title or f"Koordinat {report.lat:.4f}, {report.lng:.4f}"
        conds_list = getattr(report, "conditions", []) or []
        conds_str = ", ".join(conds_list) if conds_list else "Kenaikan debit air sungai"

        lines = [
            f"[PERINGATAN BENCANA BANJIR BANDUNG — {cond_label}]",
            f"Lokasi Kejadian: {loc_str}",
            f"Laporan: {report.title or 'Luapan Sungai'}",
            f"Kondisi Lapangan: {conds_str}",
            f"Status Pos Pantau: {cond_label} (Terverifikasi)",
            f"Diverifikasi oleh: {me.name} (Pos Pantau)",
            f"Waktu: {now.strftime('%d/%m/%y, %H.%M WIB')}",
        ]
        if reason:
            lines.append(f"Catatan Petugas: {reason.strip()}")
        if condition == "meluap":
            lines.append("TINDAKAN: Status DARURAT MELUAP! Warga di bantaran sungai dan kawasan rawan genangan segera evakuasi ke shelter aman terdekat.")
        else:
            lines.append("TINDAKAN: Status WASPADA. Warga diimbau siaga, amankan dokumen berharga, dan pantau rute evakuasi terdekat.")
        lines.append("Riksa Warga Kota Bandung — Saling Jaga, Saling Kabari")

        alert = emit(
            db,
            kind=AlertKind.LEVEL,
            level=alert_lvl,
            verification=Verification.TERVERIFIKASI,
            audience_region_id=report.region_id,
            internal=False,  # Siarkan ke semua role!
            message="\n".join(lines),
            incident_id=report.incident_id,
            created_by=me.id,
            reason=f"Verifikasi laporan warga #{report.id} ({cond_label}) oleh {me.name}",
            sms=True,
            now=now,
        )
        if alert:
            alerts.append(alert)

    db.commit()
    notifier.schedule(background, db, alerts)
    return report


@router.post("/{report_id}/verify", response_model=ReportOut)
@engine.locked
def verify_report(report_id: int, body: NoteIn, background: BackgroundTasks, db: Session = Depends(get_db),
                  me: User = Depends(coordinator)):
    return _review(db, me, report_id, ReportStatus.TERVERIFIKASI, body.note, background, condition=body.condition)


@router.post("/{report_id}/reject", response_model=ReportOut)
@engine.locked
def reject_report(report_id: int, body: ReasonIn, background: BackgroundTasks, db: Session = Depends(get_db),
                  me: User = Depends(coordinator)):
    return _review(db, me, report_id, ReportStatus.DITOLAK, body.reason, background)
