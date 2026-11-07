"""Distribusi alert ke Telegram dan SMS. Alert sudah tersimpan (kanal aplikasi) sebelum fungsi ini jalan,
jadi kegagalan satu kanal tidak menghilangkan alert maupun menghentikan kanal lain (PRD §7.3)."""
import logging
from datetime import timedelta

import httpx
from fastapi import BackgroundTasks
from sqlalchemy import func, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.auth import city_scope_ids, region_ancestor_ids, region_scope_ids
from app.config import settings
from app.db import utcnow
from app.models import Alert, AlertDelivery, AlertKind, DeliveryStatus, Role, User
from app.services.sms import mask_phone, normalize_phone, send_sms, short_text

log = logging.getLogger("riksa.notifier")
TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"
CHANNEL = "telegram"
FOLLOW_UP_KINDS = (AlertKind.KOREKSI, AlertKind.PEMBATALAN, AlertKind.SELESAI, AlertKind.LEVEL)
# Peran yang bertugas lintas wilayah (seluruh kota); sisanya menerima sesuai wilayahnya.
CITYWIDE_ROLES = {Role.TIM_SAR, Role.POS_PANTAU}
DEFAULT_INTERNAL_ROLES = [Role.KOORDINATOR.value, Role.POS_PANTAU.value]
# Alert internal yang tetap menjangkau Tim SAR di seluruh kota (permintaan bantuan & warga butuh bantuan)
CITYWIDE_INTERNAL_KINDS = {AlertKind.TUGAS, AlertKind.BANTUAN}


def schedule(background: BackgroundTasks, db: Session, alerts: list[Alert | None]) -> None:
    ids = [a.id for a in alerts if a is not None]
    if ids:
        background.add_task(deliver, db.get_bind(), ids)


def audience_users(db: Session, alert: Alert) -> list[User]:
    """Pengguna aktif penerima alert. Admin TIDAK PERNAH menerima (PRD §5.3)."""
    roles = alert.target_roles or (DEFAULT_INTERNAL_ROLES if alert.internal else
                                   [r.value for r in Role if r != Role.ADMIN])
    roles = [r for r in roles if r != Role.ADMIN.value]
    if not roles:
        return []
    users = db.scalars(select(User).where(User.is_active.is_(True), User.role.in_(roles))).all()
    local = region_scope_ids(db, alert.audience_region_id) | set(region_ancestor_ids(db, alert.audience_region_id))
    city = city_scope_ids(db, alert.audience_region_id)
    citywide = (not alert.internal) or alert.kind in CITYWIDE_INTERNAL_KINDS
    out = []
    for u in users:
        if u.role in CITYWIDE_ROLES and citywide:
            if u.region_id in city:
                out.append(u)
        elif u.region_id in local:
            out.append(u)
    return out


def send_telegram(chat_id: str, text: str) -> tuple[DeliveryStatus, str | None]:
    if settings.telegram_mode == "mock":
        return DeliveryStatus.MOCK, None
    if not settings.telegram_bot_token:
        return DeliveryStatus.GAGAL, "TELEGRAM_BOT_TOKEN kosong"
    try:
        r = httpx.post(TELEGRAM_URL.format(token=settings.telegram_bot_token),
                       json={"chat_id": chat_id, "text": text}, timeout=10)
        if r.status_code == 200 and r.json().get("ok"):
            return DeliveryStatus.TERKIRIM, None
        try:
            reason = r.json().get("description", "")  # mis. "Forbidden: bot can't initiate conversation"
        except ValueError:
            reason = ""
        return DeliveryStatus.GAGAL, f"HTTP {r.status_code} {reason}"[:255]
    except httpx.HTTPError as e:
        # jangan simpan str(e): URL request berisi token bot
        return DeliveryStatus.GAGAL, type(e).__name__


def _sms_count_last_hour(db: Session, masked: str) -> int:
    return db.scalar(select(func.count(AlertDelivery.id)).where(
        AlertDelivery.channel == "sms", AlertDelivery.recipient == masked,
        AlertDelivery.created_at >= utcnow() - timedelta(hours=1),
        AlertDelivery.status != DeliveryStatus.GAGAL)) or 0


def deliver(bind: Engine | Connection, alert_ids: list[int]) -> None:
    with Session(bind=bind) as db:
        for alert_id in alert_ids:
            alert = db.get(Alert, alert_id)
            if alert is None:
                continue
            users = audience_users(db, alert)

            # 1. Telegram: tiap chat ID sekali; chat bawaan (grup uji/monitor) selalu ikut bila diisi
            chats = {u.telegram_chat_id for u in users if u.telegram_chat_id}
            if settings.telegram_default_chat_id:
                chats.add(settings.telegram_default_chat_id)
            if alert.incident_id is not None and alert.kind in FOLLOW_UP_KINDS:
                # pembaruan/koreksi/pembatalan wajib sampai ke semua penerima alert sebelumnya (PRD §9.5)
                prev = (select(AlertDelivery.recipient).join(Alert, Alert.id == AlertDelivery.alert_id)
                        .where(Alert.incident_id == alert.incident_id, Alert.id != alert.id,
                               Alert.internal.is_(False), AlertDelivery.channel == CHANNEL))
                chats |= set(db.scalars(prev))
            for chat_id in sorted(chats):
                status, error = send_telegram(chat_id, alert.message)
                if status == DeliveryStatus.GAGAL:
                    log.warning("Telegram gagal alert=%s chat=%s err=%s", alert_id, chat_id, error)
                db.add(AlertDelivery(alert_id=alert_id, channel=CHANNEL, recipient=chat_id, status=status, error=error))

            # 2. SMS: hanya peristiwa berat (alert.sms), nomor valid, sudah opt-in, dibatasi per jam
            if alert.sms:
                text = short_text(alert.message)
                seen: set[str] = set()
                for u in users:
                    phone = normalize_phone(u.phone)
                    if not (u.sms_opt_in and phone) or phone in seen:
                        continue
                    seen.add(phone)
                    masked = mask_phone(phone)
                    if _sms_count_last_hour(db, masked) >= settings.sms_max_per_hour:
                        db.add(AlertDelivery(alert_id=alert_id, channel="sms", recipient=masked,
                                             status=DeliveryStatus.GAGAL, error="Dibatasi: batas SMS per jam"))
                        continue
                    status, error = send_sms(phone, text)
                    if status == DeliveryStatus.GAGAL:
                        log.warning("SMS gagal alert=%s to=%s err=%s", alert_id, masked, error)
                    db.add(AlertDelivery(alert_id=alert_id, channel="sms", recipient=masked, status=status, error=error))
            db.commit()  # per alert: kegagalan satu alert tidak membatalkan catatan yang lain
