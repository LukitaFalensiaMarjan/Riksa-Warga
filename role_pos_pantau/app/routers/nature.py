"""Kondisi alam (sungai berbagai daerah, hujan) + prediksi risiko untuk semua role kecuali admin (PRD v2 §7.1)."""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth import NATURE_ROLES, require_role
from app.db import get_db, utcnow
from app.models import Station, User
from app.services import nature

router = APIRouter(prefix="/nature", tags=["kondisi alam"])


@router.get("")
def nature_overview(db: Session = Depends(get_db), _: User = Depends(require_role(*NATURE_ROLES))):
    """Pos pantau seluruh kota (kondisi 3 tingkat, tinggi air, tren, perkiraan waktu mencapai ambang),
    prakiraan hujan per kelurahan, dan prediksi risiko. Data kedaluwarsa tidak tampil sebagai nilai sekarang."""
    return nature.overview(db, utcnow())


@router.get("/live")
def nature_live(db: Session = Depends(get_db), _: User = Depends(require_role(*NATURE_ROLES))):
    """Live Monitoring: cuaca Kota Bandung (Open-Meteo) + TMA semua pos (diperbarui tiap tick simulator)."""
    return nature.live(db, utcnow())


@router.get("/stations/{station_id}")
def nature_station(station_id: int, db: Session = Depends(get_db), _: User = Depends(require_role(*NATURE_ROLES))):
    """Detail pos pantau: TMA, status, tren, batas, koordinat, catatan, grafik 12 jam."""
    station = db.get(Station, station_id)
    if station is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pos pantau tidak ditemukan")
    return nature.station_detail(db, station, utcnow())
