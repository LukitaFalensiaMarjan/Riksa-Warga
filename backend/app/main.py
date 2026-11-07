import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import SessionLocal, utcnow
from app.routers import (
    alerts,
    auth,
    context,
    dashboard,
    evacuation,
    incidents,
    regions,
    reports,
    residents,
    routes,
    shelters,
    stations,
    tasks,
    users,
)
from app.services import disaster, engine, forecast, notifier
from app.services.simulator import simulation_loop

log = logging.getLogger("riksa")


def run_tick() -> None:
    """Satu putaran otomatis: usulan eskalasi tertunda, prediksi risiko, dugaan butuh bantuan, retensi lokasi."""
    try:
        forecast.fetch_hourly()  # unduh prakiraan di luar kunci (HTTP lambat); hasilnya di-cache
    except Exception:
        log.exception("Prefetch prakiraan gagal")
    fired: list = []
    with SessionLocal() as db:
        with engine.LOCK:
            now = utcnow()
            for step in (engine.tick, forecast.notify_predictions, disaster.apply_diduga):
                try:
                    fired += step(db, now) or []
                    db.commit()
                except Exception:  # satu langkah gagal tidak menghentikan yang lain
                    db.rollback()
                    log.exception("Langkah tick gagal: %s", step.__name__)
            try:
                disaster.purge_old_locations(db, now)
                db.commit()
            except Exception:
                db.rollback()
                log.exception("Retensi lokasi gagal")
        ids = [a.id for a in fired if a is not None]
        if ids:  # kirim Telegram/SMS di luar kunci agar request lain tidak menunggu
            notifier.deliver(db.get_bind(), ids)


async def _tick_loop() -> None:
    while True:
        await asyncio.sleep(settings.engine_tick_seconds)
        try:
            await asyncio.to_thread(run_tick)
        except Exception:  # loop timer tidak boleh mati karena satu kegagalan
            log.exception("Tick eskalasi gagal")


@asynccontextmanager
async def lifespan(_: FastAPI):
    task_tick = asyncio.create_task(_tick_loop()) if settings.engine_tick_seconds > 0 else None
    task_sim = (
        asyncio.create_task(simulation_loop(settings.simulator_interval_seconds))
        if settings.simulator_interval_seconds > 0
        else None
    )
    yield
    if task_tick:
        task_tick.cancel()
    if task_sim:
        task_sim.cancel()


app = FastAPI(title="Riksa Warga API", version="0.2.0", lifespan=lifespan)
for r in (auth, users, regions, reports, stations, incidents, alerts, residents, shelters, context, dashboard,
          tasks, evacuation, routes):
    app.include_router(r.router)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/config")
def public_config():
    """Konfigurasi peta untuk UI (tanpa rahasia)."""
    return {"tile_url": settings.tile_url, "tile_attribution": settings.tile_attribution,
            "routing_enabled": bool(settings.routing_url)}


# UI sederhana (tanpa build). Dipasang terakhir agar rute API di atas diproses lebih dulu.
app.mount("/", StaticFiles(directory=Path(__file__).resolve().parent.parent / "static", html=True), name="ui")
