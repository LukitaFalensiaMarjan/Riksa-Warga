"""Distribusi alert: dashboard (sudah tersimpan) + Telegram + SMS. Alert sudah tersimpan sebelum fungsi ini jalan,
jadi kegagalan satu kanal tidak menghilangkan alert dan tidak menghentikan kanal lain.

Pesan tidak memuat data warga rentan/lokasi (PRD v2 §7.3). Admin tidak pernah menjadi penerima."""
import logging

import httpx
from fastapi import BackgroundTasks
from sqlalchemy import and_, or_, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.auth import region_ancestor_ids, region_scope_ids
from app.config import settings
from app.models import Alert, AlertDelivery, AlertKind, DeliveryStatus, Role, User
from app.services.messages import FOOTER

log = logging.getLogger("riksa.notifier")
TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"
CHANNEL = "telegram"
SMS_CHANNEL = "sms"
FOLLOW_UP_KINDS = (AlertKind.KOREKSI, AlertKind.PEMBATALAN, AlertKind.SELESAI, AlertKind.LEVEL)
SMS_MAX_CHARS = 300


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


def sms_text(text: str) -> str:
    """Ringkas untuk SMS: judul + isi utama, tanpa footer panjang."""
    lines = [ln for ln in text.split("\n") if ln.strip() and ln.strip() != FOOTER]
    return " | ".join(lines)[:SMS_MAX_CHARS]


def send_sms(phone: str, text: str) -> tuple[DeliveryStatus, str | None]:
    """mock = dicatat saja. live = POST JSON ke sms_api_url (sesuaikan format dengan penyedia pilihan, PRD D-03)."""
    if settings.sms_mode == "mock":
        return DeliveryStatus.MOCK, None
    if not settings.sms_api_url or not settings.sms_api_key:
        return DeliveryStatus.GAGAL, "SMS_API_URL/SMS_API_KEY kosong"
    try:
        r = httpx.post(settings.sms_api_url, timeout=10, headers={"Authorization": f"Bearer {settings.sms_api_key}"},
                       json={"to": phone, "message": sms_text(text), "sender": settings.sms_sender})
        if 200 <= r.status_code < 300:
            return DeliveryStatus.TERKIRIM, None
        return DeliveryStatus.GAGAL, f"HTTP {r.status_code}"
    except httpx.HTTPError as e:
        return DeliveryStatus.GAGAL, type(e).__name__  # URL/kunci tidak disimpan di log


def schedule(background: BackgroundTasks, db: Session, alerts: list[Alert]) -> None:
    if alerts:
        background.add_task(deliver, db.get_bind(), [a.id for a in alerts])


def audience(db: Session, alert: Alert) -> list[User]:
    """Penerima alert (tanpa admin). Internal: koordinator/pos pantau yang membawahi lokasi (permintaan bantuan:
    koordinator + seluruh Tim SAR). Publik: semua pengguna di wilayah sasaran + seluruh Tim SAR."""
    not_admin = (User.is_active.is_(True), User.role != Role.ADMIN)
    if alert.internal:
        ancestors = region_ancestor_ids(db, alert.audience_region_id)
        if alert.kind == AlertKind.BANTUAN:  # agregat per kelurahan: koordinator RW/RT di bawahnya ikut menerima
            reach = set(ancestors) | region_scope_ids(db, alert.audience_region_id)
            cond = or_(and_(User.role == Role.KOORDINATOR, User.region_id.in_(reach)), User.role == Role.TIM_SAR)
        else:
            cond = and_(User.role.in_((Role.KOORDINATOR, Role.POS_PANTAU)), User.region_id.in_(ancestors))
        return list(db.scalars(select(User).where(cond, *not_admin)))
    scope = region_scope_ids(db, alert.audience_region_id)
    return list(db.scalars(select(User).where(or_(User.region_id.in_(scope), User.role == Role.TIM_SAR), *not_admin)))


def _previous_recipients(db: Session, alert: Alert, channel: str) -> set[str]:
    """Koreksi/pembatalan wajib sampai ke semua penerima alert sebelumnya (PRD §9.5)."""
    if alert.kind not in FOLLOW_UP_KINDS:
        return set()
    if alert.incident_id is not None:
        related = (Alert.incident_id == alert.incident_id, Alert.id != alert.id)
    elif alert.parent_id is not None:  # koreksi pengumuman: aslinya + koreksi sebelumnya
        related = (or_(Alert.id == alert.parent_id, Alert.parent_id == alert.parent_id), Alert.id != alert.id)
    else:
        return set()
    q = (select(AlertDelivery.recipient).join(Alert, Alert.id == AlertDelivery.alert_id)
         .where(*related, Alert.internal.is_(False), AlertDelivery.channel == channel))
    return set(db.scalars(q))


def recipients(db: Session, alert: Alert) -> list[str]:
    """Chat ID Telegram penerima."""
    chats = {u.telegram_chat_id for u in audience(db, alert) if u.telegram_chat_id}
    if not alert.internal and settings.telegram_default_chat_id:
        chats.add(settings.telegram_default_chat_id)
    if not alert.internal:
        chats |= _previous_recipients(db, alert, CHANNEL)
    return sorted(chats)


def sms_recipients(db: Session, alert: Alert) -> list[str]:
    if not alert.sms:
        return []
    phones = {u.phone for u in audience(db, alert) if u.phone}
    if not alert.internal:
        phones |= _previous_recipients(db, alert, SMS_CHANNEL)
    return sorted(phones)


def deliver(bind: Engine | Connection, alert_ids: list[int]) -> None:
    with Session(bind=bind) as db:
        for alert_id in alert_ids:
            alert = db.get(Alert, alert_id)
            if alert is None:
                continue
            for channel, sender, targets in ((CHANNEL, send_telegram, recipients(db, alert)),
                                             (SMS_CHANNEL, send_sms, sms_recipients(db, alert))):
                for target in targets:
                    try:
                        status, error = sender(target, alert.message)
                    except Exception as e:  # satu kanal rusak tidak boleh menghentikan yang lain
                        status, error = DeliveryStatus.GAGAL, type(e).__name__
                    if status == DeliveryStatus.GAGAL:
                        log.warning("%s gagal alert=%s err=%s", channel, alert_id, error)
                    db.add(AlertDelivery(alert_id=alert_id, channel=channel, recipient=target, status=status,
                                         error=error))
        db.commit()
