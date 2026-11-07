from datetime import datetime
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import ensure_region_access, get_current_user, require_role
from app.db import get_db, utcnow
from app.models import IntegrationSource, Region, Role, User
from app.services import engine, integrations, notifier

router = APIRouter(prefix="/integrations", tags=["integrasi"])
admin_only = require_role(Role.ADMIN)


class IntegrationIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    kind: Literal["bmkg"]
    config: dict
    poll_interval_seconds: int = Field(default=900, ge=60, le=86400)
    enabled: bool = True


class IntegrationPatch(BaseModel):
    config: dict | None = None
    poll_interval_seconds: int | None = Field(default=None, ge=60, le=86400)
    enabled: bool | None = None


def _check_config(db: Session, cfg: dict) -> dict:
    """Konfigurasi BMKG: region_id (wilayah penerima konteks cuaca), adm4 (kode BMKG), rain_mm (opsional)."""
    region_id, adm4, rain = cfg.get("region_id"), str(cfg.get("adm4", "")), cfg.get("rain_mm", integrations.DEFAULT_RAIN_MM)
    if not isinstance(region_id, int) or db.get(Region, region_id) is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "config.region_id harus wilayah yang ada")
    parts = adm4.split(".")
    if len(parts) != 4 or not all(p.isdigit() for p in parts):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "config.adm4 harus berformat 32.73.01.1001")
    if isinstance(rain, bool) or not isinstance(rain, (int, float)) or rain < 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "config.rain_mm harus angka >= 0")
    return {"region_id": region_id, "adm4": adm4, "rain_mm": float(rain)}


def _iso(dt: datetime | None) -> str | None:
    return None if dt is None else dt.isoformat() + "Z"


def _view(src: IntegrationSource, now: datetime, admin: bool) -> dict:
    stale = src.last_success is None or (now - src.last_success).total_seconds() > 2 * src.poll_interval_seconds
    out = {"id": src.id, "name": src.name, "kind": src.kind, "enabled": src.enabled, "status": src.status,
           "poll_interval_seconds": src.poll_interval_seconds, "last_sync": _iso(src.last_sync),
           "last_success": _iso(src.last_success), "stale": stale}
    if admin:  # detail galat & konfigurasi hanya untuk admin
        out.update(last_error=src.last_error, config=src.config)
    return out


@router.get("")
def list_integrations(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    now = utcnow()
    return [_view(s, now, me.role == Role.ADMIN) for s in db.scalars(select(IntegrationSource).order_by(IntegrationSource.id))]


@router.post("", status_code=status.HTTP_201_CREATED)
def create_integration(body: IntegrationIn, db: Session = Depends(get_db), me: User = Depends(admin_only)):
    if db.scalar(select(IntegrationSource.id).where(IntegrationSource.name == body.name)):
        raise HTTPException(status.HTTP_409_CONFLICT, "Nama sumber sudah dipakai")
    src = IntegrationSource(name=body.name, kind=body.kind, config=_check_config(db, body.config),
                            poll_interval_seconds=body.poll_interval_seconds, enabled=body.enabled)
    db.add(src)
    db.flush()
    log_action(db, actor_id=me.id, action="integration.create", entity_type="integration", entity_id=src.id,
               new={"name": src.name, "kind": src.kind, "config": src.config})
    db.commit()
    return _view(src, utcnow(), True)


@router.patch("/{source_id}")
def update_integration(source_id: int, body: IntegrationPatch, db: Session = Depends(get_db),
                       me: User = Depends(admin_only)):
    src = db.get(IntegrationSource, source_id)
    if src is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sumber tidak ditemukan")
    changes = body.model_dump(exclude_unset=True)
    if "config" in changes:
        changes["config"] = _check_config(db, changes["config"] or {})
    old = {k: getattr(src, k) for k in changes}
    for k, v in changes.items():
        setattr(src, k, v)
    log_action(db, actor_id=me.id, action="integration.update", entity_type="integration", entity_id=src.id,
               old=old, new=changes)
    db.commit()
    return _view(src, utcnow(), True)


@router.post("/{source_id}/sync")
@engine.locked
def sync_now(source_id: int, background: BackgroundTasks, db: Session = Depends(get_db),
             me: User = Depends(require_role(Role.ADMIN, Role.POS_PANTAU))):
    src = db.get(IntegrationSource, source_id)
    if src is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Sumber tidak ditemukan")
    if me.role != Role.ADMIN:
        region_id = (src.config or {}).get("region_id")
        if region_id is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Hanya admin yang dapat menyinkronkan sumber ini")
        ensure_region_access(db, me, region_id)
    alerts = integrations.sync_source(db, src, utcnow())
    log_action(db, actor_id=me.id, action="integration.sync", entity_type="integration", entity_id=src.id,
               new={"status": src.status})
    db.commit()
    notifier.schedule(background, db, alerts)
    return _view(src, utcnow(), me.role == Role.ADMIN)
