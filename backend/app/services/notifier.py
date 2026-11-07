"""Distribusi alert ke Telegram. Alert sudah tersimpan (kanal dashboard) sebelum fungsi ini jalan,
jadi kegagalan kanal tidak menghilangkan alert."""
import logging

import httpx
from fastapi import BackgroundTasks
from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.auth import region_ancestor_ids, region_scope_ids
from app.config import settings
from app.models import Alert, AlertDelivery, AlertKind, DeliveryStatus, Role, User

log = logging.getLogger("riksa.notifier")
TELEGRAM_URL = "https://api.telegram.org/bot{token}/sendMessage"
CHANNEL = "telegram"
FOLLOW_UP_KINDS = (AlertKind.KOREKSI, AlertKind.PEMBATALAN, AlertKind.SELESAI, AlertKind.LEVEL)


def schedule(background: BackgroundTasks, db: Session, alerts: list[Alert]) -> None:
    if alerts:
        background.add_task(deliver, db.get_bind(), [a.id for a in alerts])


def recipients(db: Session, alert: Alert) -> list[str]:
    active_chat = (User.is_active.is_(True), User.telegram_chat_id.is_not(None))
    if alert.internal:
        # internal hanya untuk koordinator yang membawahi lokasi kejadian
        q = select(User.telegram_chat_id).where(
            User.role == Role.KOORDINATOR, User.region_id.in_(region_ancestor_ids(db, alert.audience_region_id)),
            *active_chat)
        return sorted(set(db.scalars(q)))

    scope = region_scope_ids(db, alert.audience_region_id)
    chats = set(db.scalars(select(User.telegram_chat_id).where(User.region_id.in_(scope), *active_chat)))
    if settings.telegram_default_chat_id:
        chats.add(settings.telegram_default_chat_id)
    if alert.incident_id is not None and alert.kind in FOLLOW_UP_KINDS:
        # pembaruan/koreksi/pembatalan wajib sampai ke semua penerima alert sebelumnya (PRD §9.5)
        prev = (select(AlertDelivery.recipient).join(Alert, Alert.id == AlertDelivery.alert_id)
                .where(Alert.incident_id == alert.incident_id, Alert.id != alert.id,
                       Alert.internal.is_(False), AlertDelivery.channel == CHANNEL))
        chats |= set(db.scalars(prev))
    return sorted(chats)


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


def deliver(bind: Engine | Connection, alert_ids: list[int]) -> None:
    with Session(bind=bind) as db:
        for alert_id in alert_ids:
            alert = db.get(Alert, alert_id)
            if alert is None:
                continue
            for chat_id in recipients(db, alert):
                status, error = send_telegram(chat_id, alert.message)
                if status == DeliveryStatus.GAGAL:
                    log.warning("Telegram gagal alert=%s chat=%s err=%s", alert_id, chat_id, error)
                db.add(AlertDelivery(alert_id=alert_id, channel=CHANNEL, recipient=chat_id,
                                     status=status, error=error))
        db.commit()
