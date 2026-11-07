from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import city_scope_ids, ensure_region_access, operational_user, require_role, user_scope_ids
from app.db import get_db, utcnow
from app.models import Incident, IncidentStatus, RescueTask, Resident, Role, Shelter, User
from app.routers.tasks import FINAL
from app.schemas import IncidentOut
from app.services.disaster import hazard_zones, mode_regions
from app.services.evacuation import priorities

router = APIRouter(prefix="/evacuation", tags=["evakuasi"])
TARGET_STATUSES = ("butuh_bantuan", "diduga_butuh_bantuan")


def _latest_incident(db: Session, scope: set[int] | None) -> Incident | None:
    q = select(Incident).where(Incident.status == IncidentStatus.AKTIF)
    if scope is not None:
        q = q.where(Incident.region_id.in_(scope))
    return db.scalars(q.order_by(Incident.started_at.desc()).limit(1)).first()


@router.get("/priorities")
def evacuation_priorities(incident_id: int | None = None, db: Session = Depends(get_db),
                          me: User = Depends(require_role(Role.KOORDINATOR))):
    """Prioritas evakuasi warga di wilayah koordinator (skor transparan, alat bantu urutan pemeriksaan)."""
    scope = user_scope_ids(db, me)
    if incident_id is not None:
        incident = db.get(Incident, incident_id)
        if incident is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Kejadian tidak ditemukan")
        ensure_region_access(db, me, incident.region_id)
    else:
        incident = _latest_incident(db, scope)
    now = utcnow()
    residents_q = select(Resident)
    tasks_q = select(RescueTask).where(RescueTask.status.not_in(FINAL))
    if scope is not None:
        residents_q = residents_q.where(Resident.region_id.in_(scope))
        tasks_q = tasks_q.where(RescueTask.region_id.in_(scope))
    items = priorities(db, list(db.scalars(residents_q)), incident, list(db.scalars(select(Shelter))),
                       list(db.scalars(tasks_q)), now, mode_regions(db, now))
    # lokasi warga = data sensitif: setiap akses dicatat
    log_action(db, actor_id=me.id, action="evacuation.view", entity_type="incident",
               entity_id=incident.id if incident else None, new={"jumlah": len(items)})
    db.commit()
    return {
        "incident": IncidentOut.model_validate(incident).model_dump(mode="json") if incident else None,
        "note": "Skor adalah alat bantu urutan pemeriksaan, bukan keputusan. Status tanpa kabar tetap dicek langsung.",
        "items": items,
    }


@router.get("/rescue-targets")
def rescue_targets(db: Session = Depends(get_db), me: User = Depends(require_role(Role.TIM_SAR, Role.KOORDINATOR, Role.POS_PANTAU))):
    """Peta Tim SAR & Pos Pantau: warga yang membutuhkan / diduga membutuhkan bantuan dan masih di zona berbahaya (FR-063).

    Syarat tampil: Mode Bencana aktif di area warga, statusnya butuh bantuan atau diduga (dijawab/ditandai sejak mode
    dimulai), dan lokasinya berada di zona berbahaya. Tim SAR & Pos Pantau se-kota; koordinator hanya wilayahnya."""
    now = utcnow()
    mode = mode_regions(db, now)
    zones = hazard_zones(db)
    if me.role in (Role.TIM_SAR, Role.POS_PANTAU):
        scope: set[int] | None = city_scope_ids(db, me.region_id)
    else:
        scope = user_scope_ids(db, me)
    if mode:
        residents_q = select(Resident).where(Resident.region_id.in_(list(mode)))
    else:
        residents_q = select(Resident)
    tasks_q = select(RescueTask).where(RescueTask.status.not_in(FINAL))
    if scope is not None:
        residents_q = residents_q.where(Resident.region_id.in_(scope))
        tasks_q = tasks_q.where(RescueTask.region_id.in_(scope))
    items = priorities(db, list(db.scalars(residents_q)), _latest_incident(db, scope),
                       list(db.scalars(select(Shelter))), list(db.scalars(tasks_q)), now, mode)
    targets = [it for it in items
               if it["status"] in TARGET_STATUSES and it["lat"] is not None
               and (it["in_hazard_zone"] or not mode or it.get("task") is not None)
               and (it["status_at"] is None or not mode or it["status_at"] >= mode.get(it["region_id"], datetime.min))]
    log_action(db, actor_id=me.id, action="rescue.targets.view", entity_type="incident", entity_id=None,
               new={"jumlah": len(targets)})
    db.commit()
    return {"mode_active": bool(mode), "zones": zones, "items": targets,
            "note": "Skor hanya alat bantu prioritas. Dugaan berarti warga belum menjawab, bukan konfirmasi."}


@router.get("/mode")
def disaster_mode(db: Session = Depends(get_db), me: User = Depends(operational_user)):
    """Zona berbahaya dan area Mode Bencana untuk lapisan peta (semua role non-admin)."""
    mode = mode_regions(db)
    return {"active": bool(mode), "regions": {str(k): v for k, v in mode.items()}, "zones": hazard_zones(db)}
