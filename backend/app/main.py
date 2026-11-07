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
from app.services import engine, notifier

log = logging.getLogger("riksa")


def run_tick() -> None:
    with SessionLocal() as db:
        with engine.LOCK:
            fired = engine.tick(db, utcnow())
            db.commit()
        if fired:  # kirim Telegram di luar kunci agar request lain tidak menunggu
            notifier.deliver(db.get_bind(), [a.id for a in fired])


async def _tick_loop() -> None:
    while True:
        await asyncio.sleep(settings.engine_tick_seconds)
        try:
            await asyncio.to_thread(run_tick)
        except Exception:  # loop timer tidak boleh mati karena satu kegagalan
            log.exception("Tick eskalasi gagal")


@asynccontextmanager
async def lifespan(_: FastAPI):
    task = asyncio.create_task(_tick_loop()) if settings.engine_tick_seconds > 0 else None
    yield
    if task:
        task.cancel()


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
