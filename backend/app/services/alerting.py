"""Satu pintu pembuatan Alert (aplikasi). Pengiriman Telegram/SMS dilakukan terpisah oleh notifier."""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import utcnow
from app.models import Alert, AlertKind, AlertLevel, Verification


def emit(
    db: Session, *, kind: AlertKind, message: str, audience_region_id: int, internal: bool = False,
    level: AlertLevel | None = None, verification: Verification | None = None, incident_id: int | None = None,
    station_id: int | None = None, created_by: int | None = None, reason: str | None = None,
    target_roles: list[str] | None = None, sms: bool = False, dedupe_key: str | None = None,
    dedupe_minutes: int = 0, parent_alert_id: int | None = None, now: datetime | None = None,
) -> Alert | None:
    """Buat Alert. Dengan dedupe_key, peristiwa sama dalam dedupe_minutes tidak dibuat lagi (FR-045)."""
    now = now or utcnow()
    if dedupe_key and dedupe_minutes:
        hit = db.scalar(select(Alert.id).where(
            Alert.dedupe_key == dedupe_key, Alert.created_at >= now - timedelta(minutes=dedupe_minutes)).limit(1))
        if hit is not None:
            return None
    alert = Alert(
        incident_id=incident_id, station_id=station_id, kind=kind, level=level, verification=verification,
        audience_region_id=audience_region_id, internal=internal, message=message, reason=reason,
        created_by=created_by, created_at=now, target_roles=target_roles, sms=sms, dedupe_key=dedupe_key,
        parent_alert_id=parent_alert_id,
    )
    db.add(alert)
    db.flush()
    return alert


def alert_for_role(alert: Alert, role: str) -> bool:
    """Filter target_roles untuk tampilan dalam aplikasi."""
    return not alert.target_roles or role in alert.target_roles
