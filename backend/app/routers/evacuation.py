from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import ensure_region_access, require_role, user_scope_ids
from app.db import get_db, utcnow
from app.models import Incident, IncidentStatus, RescueTask, Resident, Role, Shelter, User
from app.routers.tasks import FINAL
from app.schemas import IncidentOut
from app.services.evacuation import priorities

router = APIRouter(prefix="/evacuation", tags=["evakuasi"])


@router.get("/priorities")
def evacuation_priorities(incident_id: int | None = None, db: Session = Depends(get_db),
                          me: User = Depends(require_role(Role.KOORDINATOR, Role.ADMIN))):
    scope = user_scope_ids(db, me)

    def scoped(q, col):
        return q if scope is None else q.where(col.in_(scope))

    if incident_id is not None:
        incident = db.get(Incident, incident_id)
        if incident is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Kejadian tidak ditemukan")
        ensure_region_access(db, me, incident.region_id)
    else:  # default: kejadian aktif terbaru di wilayahnya
        incident = db.scalars(scoped(select(Incident).where(Incident.status == IncidentStatus.AKTIF),
                                     Incident.region_id).order_by(Incident.started_at.desc()).limit(1)).first()
    residents = list(db.scalars(scoped(select(Resident), Resident.region_id)))
    shelters = list(db.scalars(select(Shelter)))
    tasks = list(db.scalars(scoped(select(RescueTask).where(RescueTask.status.not_in(FINAL)), RescueTask.region_id)))
    items = priorities(db, residents, incident, shelters, tasks, utcnow())
    # lokasi warga = data sensitif: setiap akses dicatat
    log_action(db, actor_id=me.id, action="evacuation.view", entity_type="incident",
               entity_id=incident.id if incident else None, new={"jumlah": len(items)})
    db.commit()
    return {
        "incident": IncidentOut.model_validate(incident).model_dump(mode="json") if incident else None,
        "note": "Skor adalah alat bantu urutan pemeriksaan, bukan keputusan. Status tanpa kabar tetap dicek langsung.",
        "items": items,
    }
