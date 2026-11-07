from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session

from app.auth import OPERATOR_ROLES, get_current_user, region_ancestor_ids, region_scope_ids, require_role
from app.db import get_db
from app.models import Alert, AlertDelivery, AlertKind, Role, User
from app.schemas import AlertOut, DeliveryOut

router = APIRouter(prefix="/alerts", tags=["peringatan"])


def visible_alerts(db: Session, me: User) -> Select:
    q = select(Alert)
    if me.role == Role.ADMIN:  # PRD v2: admin tidak menerima/melihat peringatan operasional
        return q.where(Alert.id < 0)
    if me.role == Role.TIM_SAR:  # Tim SAR: seluruh kota (publik) + permintaan bantuan warga
        return q.where(or_(Alert.internal.is_(False), Alert.kind == AlertKind.BANTUAN))
    ancestors = region_ancestor_ids(db, me.region_id)
    if me.role in (Role.KOORDINATOR, Role.POS_PANTAU):
        # alert internal & publik di wilayahnya + alert publik untuk wilayah induk
        return q.where(Alert.audience_region_id.in_(region_scope_ids(db, me.region_id) | set(ancestors)))
    # warga & pos pantau: hanya alert publik yang menyasar wilayahnya (RT -> RW -> kelurahan ...)
    return q.where(Alert.internal.is_(False), Alert.audience_region_id.in_(ancestors))


@router.get("", response_model=list[AlertOut])
def list_alerts(incident_id: int | None = None, limit: int = Query(50, ge=1, le=200),
                db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    q = visible_alerts(db, me).order_by(Alert.id.desc()).limit(limit)
    if incident_id is not None:
        q = q.where(Alert.incident_id == incident_id)
    return db.scalars(q).all()


@router.get("/{alert_id}/deliveries", response_model=list[DeliveryOut])
def deliveries(alert_id: int, db: Session = Depends(get_db),
               me: User = Depends(require_role(*OPERATOR_ROLES))):
    alert = db.scalar(visible_alerts(db, me).where(Alert.id == alert_id))
    if alert is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Alert tidak ditemukan")
    return db.scalars(select(AlertDelivery).where(AlertDelivery.alert_id == alert_id).order_by(AlertDelivery.id)).all()
