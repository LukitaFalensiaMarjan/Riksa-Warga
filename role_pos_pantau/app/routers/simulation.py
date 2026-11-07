from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth import ensure_region_access, require_role
from app.db import get_db, utcnow
from app.models import Role, Station, User
from app.schemas import ObservationOut
from app.services import engine, notifier, simulator

router = APIRouter(prefix="/simulation", tags=["simulasi"])


class StepIn(BaseModel):
    scenario: Literal["naik", "turun"] = "naik"


@router.post("/stations/{station_id}/step", response_model=ObservationOut, status_code=status.HTTP_201_CREATED)
@engine.locked
def simulate_step(station_id: int, background: BackgroundTasks, body: StepIn | None = None,
                  db: Session = Depends(get_db), me: User = Depends(require_role(Role.POS_PANTAU, Role.KOORDINATOR))):
    """Satu langkah simulator tinggi air (berlabel SIMULATION) untuk demo; memicu mesin aturan seperti data nyata."""
    station = db.get(Station, station_id)
    if station is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pos pantau tidak ditemukan")
    ensure_region_access(db, me, station.region_id)
    obs, alerts = simulator.step(db, station, (body or StepIn()).scenario, me, utcnow())
    db.commit()
    notifier.schedule(background, db, alerts)
    return obs
