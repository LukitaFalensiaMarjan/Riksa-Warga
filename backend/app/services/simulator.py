"""Simulator pengamatan tinggi air untuk demo (BERLABEL SIMULASI, bukan sensor nyata — PRD FR-015).

Kondisi sungai (Normal / Waspada / Meluap) ditetapkan manusia lewat tombol pos pantau dan disimpan di
`Station.condition` (bertahan saat server restart). Simulator hanya menghasilkan deretan angka tinggi air yang
konsisten dengan kondisi itu agar grafik dan tren hidup. Data lama dibersihkan berkala.
"""
import asyncio
import logging
import random
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.db import SessionLocal, utcnow
from app.models import Observation, RiverCondition, Role, SourceMode, Station, User

log = logging.getLogger("riksa.simulator")

CONDITIONS = ("normal", "waspada", "meluap")
KEEP_HOURS = 48  # pengamatan simulasi lebih lama dari ini dihapus
PRUNE_EVERY = 200  # putaran

_ticks = 0


def generate_observation_for_station(db: Session, station: Station, condition: str | None = None) -> Observation:
    """Satu pengamatan SIMULASI sesuai kondisi sungai. Commit dilakukan pemanggil bila perlu."""
    condition = condition or station.condition or "normal"
    w = float(station.warning_cm or 150.0)
    d = float(station.danger_cm or 250.0)

    if condition == "normal":
        level = max(20.0, round(w * 0.55 + random.uniform(-4.5, 4.5), 1))
        river_cond, note = RiverCondition.NORMAL, "Tinggi air normal (simulasi)"
    elif condition == "waspada":
        level = round(w + (d - w) * 0.45 + random.uniform(-5.0, 5.0), 1)
        river_cond = RiverCondition.NAIK if random.random() > 0.4 else RiverCondition.ARUS_DERAS
        note = "Debit naik, arus deras mendekati bibir tanggul (simulasi)"
    else:
        level = round(d + 25.0 + random.uniform(-3.5, 7.5), 1)
        river_cond, note = RiverCondition.MELUAP, "Air meluap ke permukiman dan badan jalan (simulasi)"

    user = (db.scalar(select(User).where(User.role == Role.POS_PANTAU, User.is_active.is_(True)).limit(1))
            or db.scalar(select(User).limit(1)))
    now = utcnow()
    obs = Observation(station_id=station.id, level_cm=level, river_condition=river_cond, note=note,
                      source_mode=SourceMode.SIMULATION, observed_at=now, received_at=now,
                      reported_by=user.id if user else 1)
    db.add(obs)
    db.flush()
    return obs


def tick_all_stations() -> None:
    """Satu putaran pembuatan pengamatan berkala untuk semua pos."""
    global _ticks
    _ticks += 1
    with SessionLocal() as db:
        for s in db.scalars(select(Station)).all():
            generate_observation_for_station(db, s)
        if _ticks % PRUNE_EVERY == 0:
            db.execute(delete(Observation).where(
                Observation.source_mode == SourceMode.SIMULATION,
                Observation.observed_at < utcnow() - timedelta(hours=KEEP_HOURS)))
        db.commit()


async def simulation_loop(interval_seconds: float = 3.0) -> None:
    log.info("Simulator tinggi air (SIMULASI) berjalan tiap %s detik", interval_seconds)
    while True:
        try:
            await asyncio.to_thread(tick_all_stations)
        except asyncio.CancelledError:
            log.info("Simulator tinggi air dihentikan")
            break
        except Exception as e:  # satu kegagalan tidak boleh mematikan loop
            log.warning("Kesalahan simulator tinggi air: %s", type(e).__name__)
        await asyncio.sleep(interval_seconds)
