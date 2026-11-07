from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import OPERATOR_ROLES, SITUATION_ROLES, ensure_region_access, require_role, user_scope_ids
from app.db import get_db, utcnow
from app.models import AuditLog, Hazard, Incident, IncidentStatus, Report, Role, User
from app.schemas import AlertOut, AuditLogOut, IncidentDetail, IncidentOut, LevelIn, NoteIn, ReasonIn
from app.services import engine, notifier

router = APIRouter(prefix="/incidents", tags=["kejadian"])
coordinator = require_role(*OPERATOR_ROLES)
viewer = require_role(*SITUATION_ROLES)


def _get(db: Session, me: User, incident_id: int) -> Incident:
    incident = db.get(Incident, incident_id)
    if incident is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Kejadian tidak ditemukan")
    ensure_region_access(db, me, incident.region_id)
    return incident


@router.get("", response_model=list[IncidentOut])
def list_incidents(
    status_: IncidentStatus | None = Query(IncidentStatus.AKTIF, alias="status"),
    hazard: Hazard | None = None,
    db: Session = Depends(get_db),
    me: User = Depends(viewer),
):
    q = select(Incident).order_by(Incident.last_report_at.desc())
    scope = user_scope_ids(db, me)
    if scope is not None:
        q = q.where(Incident.region_id.in_(scope))
    if status_:
        q = q.where(Incident.status == status_)
    if hazard:
        q = q.where(Incident.hazard == hazard)
    return db.scalars(q).all()


@router.get("/{incident_id}", response_model=IncidentDetail)
def get_incident(incident_id: int, db: Session = Depends(get_db), me: User = Depends(viewer)):
    incident = _get(db, me, incident_id)
    reports = db.scalars(select(Report).where(Report.incident_id == incident.id).order_by(Report.id)).all()
    return {**IncidentOut.model_validate(incident).model_dump(), "reports": reports}


@router.get("/{incident_id}/history", response_model=list[AuditLogOut])
def incident_history(incident_id: int, db: Session = Depends(get_db), me: User = Depends(viewer)):
    _get(db, me, incident_id)
    return db.scalars(select(AuditLog).where(
        AuditLog.entity_type == "incident", AuditLog.entity_id == str(incident_id)).order_by(AuditLog.id)).all()


@router.post("/{incident_id}/level", response_model=AlertOut)
@engine.locked
def set_level(incident_id: int, body: LevelIn, background: BackgroundTasks, db: Session = Depends(get_db),
              me: User = Depends(coordinator)):
    incident = _get(db, me, incident_id)
    alert = engine.set_level_manual(db, incident, body.level, me, body.reason, utcnow())
    db.commit()
    notifier.schedule(background, db, [alert])
    return alert


@router.post("/{incident_id}/verify", response_model=IncidentOut)
@engine.locked
def verify(incident_id: int, body: NoteIn, db: Session = Depends(get_db), me: User = Depends(coordinator)):
    incident = _get(db, me, incident_id)
    engine.verify_incident(db, incident, me, body.note, utcnow())
    db.commit()
    return incident


@router.post("/{incident_id}/proposal/dismiss", response_model=IncidentOut)
@engine.locked
def dismiss_proposal(incident_id: int, body: ReasonIn, db: Session = Depends(get_db),
                     me: User = Depends(coordinator)):
    incident = _get(db, me, incident_id)
    engine.dismiss_proposal(db, incident, me, body.reason, utcnow())
    db.commit()
    return incident


@router.post("/{incident_id}/cancel", response_model=AlertOut)
@engine.locked
def cancel(incident_id: int, body: ReasonIn, background: BackgroundTasks, db: Session = Depends(get_db),
           me: User = Depends(coordinator)):
    incident = _get(db, me, incident_id)
    alert = engine.cancel_incident(db, incident, me, body.reason, utcnow())
    db.commit()
    notifier.schedule(background, db, [alert])
    return alert


@router.post("/{incident_id}/close", response_model=AlertOut)
@engine.locked
def close(incident_id: int, body: ReasonIn, background: BackgroundTasks, db: Session = Depends(get_db),
          me: User = Depends(coordinator)):
    incident = _get(db, me, incident_id)
    alert = engine.close_incident(db, incident, me, body.reason, utcnow())
    db.commit()
    notifier.schedule(background, db, [alert])
    return alert
