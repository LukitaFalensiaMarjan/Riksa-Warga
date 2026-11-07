"""Peta Tim SAR: warga yang membutuhkan bantuan / diduga butuh bantuan di area berbahaya (PRD v2 §6.4)."""
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import require_role, user_scope_ids
from app.db import get_db, utcnow
from app.models import RescueTask, Resident, Role, Shelter, User
from app.routers.tasks import FINAL
from app.services.disaster import live_location_visible
from app.services.evacuation import priorities

router = APIRouter(prefix="/sar", tags=["tim sar"])
NEED_STATUSES = {"butuh_bantuan", "duga_butuh_bantuan"}


@router.get("/needs")
def needs(db: Session = Depends(get_db), me: User = Depends(require_role(Role.TIM_SAR))):
    """Hanya warga di area dengan Mode Bencana aktif. Lokasi = data sensitif: setiap akses dicatat."""
    now = utcnow()
    scope = user_scope_ids(db, me)
    q = select(Resident)
    if scope is not None:
        q = q.where(Resident.region_id.in_(scope))
    cache: dict = {}
    residents = [r for r in db.scalars(q) if live_location_visible(db, r.region_id, now, cache)]
    tasks = list(db.scalars(select(RescueTask).where(RescueTask.status.not_in(FINAL))))
    items = [i for i in priorities(db, residents, None, list(db.scalars(select(Shelter))), tasks, now)
             if i["status"] in NEED_STATUSES]
    log_action(db, actor_id=me.id, action="sar.needs.view", entity_type="resident", new={"jumlah": len(items)})
    db.commit()
    return {
        "disaster_active": bool(residents),
        "note": ("Skor adalah alat bantu urutan, bukan keputusan. 'Diduga butuh bantuan' = belum menjawab di area "
                 "berbahaya (bukan konfirmasi). Peta hanya aktif saat Mode Bencana."),
        "items": items,
    }
