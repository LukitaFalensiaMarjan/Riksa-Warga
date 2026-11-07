from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import Select, and_, or_, select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import (
    city_root_id,
    city_scope_ids,
    ensure_city_access,
    ensure_region_access,
    operational_user,
    region_ancestor_ids,
    region_scope_ids,
    require_role,
)
from app.db import get_db, utcnow
from app.models import Alert, AlertDelivery, AlertKind, AlertLevel, Region, Report, ReportStatus, Role, User, Verification
from app.schemas import AlertCorrectIn, AlertOut, BroadcastAlertIn, DeliveryOut
from app.services import notifier
from app.services.alerting import alert_for_role, emit
from app.services.messages import FOOTER, fmt_time

router = APIRouter(prefix="/alerts", tags=["peringatan"])
pos_pantau_only = require_role(Role.POS_PANTAU)

LEVEL_ACTION = {
    AlertLevel.PANTAU: "Tetap tenang dan pantau informasi berikutnya.",
    AlertLevel.WASPADA: "Pantau informasi, jauhi bantaran sungai, siapkan dokumen penting, obat, dan tas siaga.",
    AlertLevel.SIAGA: "Bersiap mengungsi: amankan dokumen dan obat, bantu tetangga rentan bila aman, kenali shelter terdekat.",
    AlertLevel.EVAKUASI: ("Sungai meluap. Segera menuju shelter aman terdekat sesuai arahan petugas, buka aplikasi lalu "
                          "laporkan Saya Aman / Butuh Bantuan. Jangan melewati arus air."),
}
LEVEL_LABEL = {AlertLevel.PANTAU: "INFO", AlertLevel.WASPADA: "WASPADA", AlertLevel.SIAGA: "SIAGA",
               AlertLevel.EVAKUASI: "MELUAP / EVAKUASI"}
CORRECTABLE = (AlertKind.PENGUMUMAN, AlertKind.SUNGAI, AlertKind.LEVEL, AlertKind.PREDIKSI)


def visible_alerts(db: Session, me: User) -> Select:
    """Alert yang boleh dilihat pengguna. Admin tidak pernah (dicegah operational_user)."""
    local = region_scope_ids(db, me.region_id) | set(region_ancestor_ids(db, me.region_id))
    q = select(Alert)
    if me.role in (Role.POS_PANTAU, Role.TIM_SAR):
        city = city_scope_ids(db, me.region_id)
        cond = or_(and_(Alert.internal.is_(False), Alert.audience_region_id.in_(city)),
                   Alert.audience_region_id.in_(local))
        if me.role == Role.TIM_SAR:  # permintaan bantuan & warga butuh bantuan menjangkau SAR se-kota
            cond = or_(cond, and_(Alert.kind.in_([AlertKind.TUGAS, AlertKind.BANTUAN]),
                                  Alert.audience_region_id.in_(city)))
        return q.where(cond)
    if me.role == Role.KOORDINATOR:
        return q.where(Alert.audience_region_id.in_(local))
    return q.where(Alert.internal.is_(False), Alert.audience_region_id.in_(local))  # warga


def filter_for_role(alerts: list[Alert], me: User) -> list[Alert]:
    return [a for a in alerts if alert_for_role(a, me.role.value)]


@router.get("", response_model=list[AlertOut])
def list_alerts(incident_id: int | None = None, limit: int = Query(50, ge=1, le=200),
                db: Session = Depends(get_db), me: User = Depends(operational_user)):
    q = visible_alerts(db, me).order_by(Alert.id.desc()).limit(limit * 3)
    if incident_id is not None:
        q = q.where(Alert.incident_id == incident_id)
    return filter_for_role(list(db.scalars(q).all()), me)[:limit]


@router.post("/broadcast", response_model=AlertOut, status_code=status.HTTP_201_CREATED)
def broadcast_alert(body: BroadcastAlertIn, background: BackgroundTasks, db: Session = Depends(get_db),
                    me: User = Depends(pos_pantau_only)):
    """Pengumuman pos pantau ke semua role non-admin lewat aplikasi, Telegram, dan SMS (FR-028).

    Dasar wajib: laporan yang sudah diverifikasi, atau catatan pengamatan langsung (PRD §7.2)."""
    basis = None
    if body.basis_report_id is not None:
        report = db.get(Report, body.basis_report_id)
        if report is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Laporan dasar tidak ditemukan")
        ensure_region_access(db, me, report.region_id)
        if report.status != ReportStatus.TERVERIFIKASI:
            raise HTTPException(status.HTTP_409_CONFLICT, "Laporan dasar harus diverifikasi lebih dulu")
        basis = f"laporan #{report.id} terverifikasi"
    elif body.basis_note and body.basis_note.strip():
        basis = "pengamatan langsung: " + body.basis_note.strip()
    else:
        basis = "pengamatan pos pantau"

    audience = body.region_id or city_root_id(db, me.region_id)
    region = db.get(Region, audience)
    if region is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Wilayah sasaran tidak ditemukan")
    ensure_city_access(db, me, audience)
    now = utcnow()
    label = LEVEL_LABEL[body.level]
    nl = chr(10)
    text = nl.join([
        f"[RIKSA WARGA — PENGUMUMAN {label}]",
        f"Wilayah: {region.name}",
        f"Waktu: {fmt_time(now)}",
        f"Status: {label} — TERVERIFIKASI pos pantau ({me.name})",
        "", body.message.strip(), f"Dasar: {basis}",
        f"Tindakan: {LEVEL_ACTION[body.level]}", FOOTER,
    ])
    alert = emit(db, kind=AlertKind.PENGUMUMAN, level=body.level, verification=Verification.TERVERIFIKASI,
                 audience_region_id=audience, message=text, created_by=me.id, sms=True, now=now,
                 reason=f"Dasar: {basis}")
    log_action(db, actor_id=me.id, action="alert.broadcast", entity_type="alert", entity_id=alert.id,
               new={"level": body.level.value, "audience": audience, "dasar": basis})
    db.commit()
    notifier.schedule(background, db, [alert])
    return alert


@router.post("/{alert_id}/correct", response_model=AlertOut, status_code=status.HTTP_201_CREATED)
def correct_alert(alert_id: int, body: AlertCorrectIn, background: BackgroundTasks, db: Session = Depends(get_db),
                  me: User = Depends(pos_pantau_only)):
    """Koreksi/pembatalan pengumuman: dikirim ke audiens & kanal yang sama, riwayat tetap tersimpan (FR-029)."""
    orig = db.scalar(visible_alerts(db, me).where(Alert.id == alert_id))
    if orig is None or orig.kind not in CORRECTABLE or orig.internal:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pengumuman tidak ditemukan atau tidak bisa dikoreksi")
    if not body.cancel and not (body.message and body.message.strip()):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Pesan koreksi wajib diisi")
    now = utcnow()
    nl = chr(10)
    first = orig.message.splitlines()[0] if orig.message else ""
    if body.cancel:
        kind, title = AlertKind.PEMBATALAN, "PEMBATALAN PENGUMUMAN"
        content = f"Pengumuman #{orig.id} DIBATALKAN. Abaikan pesan sebelumnya ({first})."
        level = None
    else:
        kind, title = AlertKind.KOREKSI, "KOREKSI PENGUMUMAN"
        content = f"Koreksi atas pengumuman #{orig.id}: {body.message.strip()}"
        level = orig.level
    text = nl.join([f"[RIKSA WARGA — {title}]", f"Waktu: {fmt_time(now)}", content,
                    f"Alasan: {body.reason.strip()}", FOOTER])
    alert = emit(db, kind=kind, level=level, verification=Verification.TERVERIFIKASI,
                 audience_region_id=orig.audience_region_id, message=text, created_by=me.id, sms=True, now=now,
                 reason=body.reason.strip(), incident_id=orig.incident_id, station_id=orig.station_id,
                 target_roles=orig.target_roles, parent_alert_id=orig.id)
    log_action(db, actor_id=me.id, action="alert.cancel" if body.cancel else "alert.correct", entity_type="alert",
               entity_id=orig.id, new={"alert_baru": alert.id}, reason=body.reason)
    db.commit()
    notifier.schedule(background, db, [alert])
    return alert


@router.get("/{alert_id}/deliveries", response_model=list[DeliveryOut])
def deliveries(alert_id: int, db: Session = Depends(get_db),
               me: User = Depends(require_role(Role.KOORDINATOR, Role.POS_PANTAU))):
    alert = db.scalar(visible_alerts(db, me).where(Alert.id == alert_id))
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert tidak ditemukan")
    return db.scalars(select(AlertDelivery).where(AlertDelivery.alert_id == alert_id).order_by(AlertDelivery.id)).all()
