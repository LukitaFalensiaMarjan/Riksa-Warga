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
    announcements,
    auth,
    context,
    dashboard,
    evacuation,
    incidents,
    integrations,
    nature,
    regions,
    reports,
    residents,
    routes,
    sar,
    shelters,
    simulation,
    stations,
    tasks,
    users,
)
from app.services import disaster, engine, integrations as integration_svc, live_sim, nature as nature_svc, notifier

log = logging.getLogger("riksa")


def run_tick() -> None:
    with SessionLocal() as db:
        with engine.LOCK:
            now = utcnow()
            fired = engine.tick(db, now)
            fired += integration_svc.sync_due(db, now)  # sumber gagal hanya mengubah statusnya
            fired += disaster.unconfirmed_tick(db, now)  # Diduga Butuh Bantuan (PRD v2 §9.3)
            fired += nature_svc.prediction_tick(db, now)  # notifikasi bila risiko naik
            disaster.purge_locations(db, now)  # retensi lokasi
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


def run_live_sim() -> None:
    with SessionLocal() as db:
        fired = live_sim.run_once(db, utcnow())
        if fired:
            notifier.deliver(db.get_bind(), [a.id for a in fired])


def seed_live_history() -> None:
    with SessionLocal() as db:
        with engine.LOCK:
            live_sim.seed_history(db, utcnow())
            db.commit()


async def _live_loop() -> None:
    try:
        await asyncio.to_thread(seed_live_history)  # grafik 12 jam langsung terisi
    except Exception:
        log.exception("Riwayat simulator gagal dibuat")
    while True:
        await asyncio.sleep(settings.live_sim_seconds)
        try:
            await asyncio.to_thread(run_live_sim)
        except Exception:  # loop tidak boleh mati karena satu kegagalan
            log.exception("Tick simulator TMA gagal")


@asynccontextmanager
async def lifespan(_: FastAPI):
    tasks = []
    if settings.telegram_mode != "live":  # env var TELEGRAM_MODE di terminal mengalahkan .env
        log.warning("TELEGRAM_MODE=%s: notifikasi Telegram HANYA dicatat, tidak dikirim ke HP. "
                    "Hapus env var TELEGRAM_MODE atau set ke live lalu restart server.", settings.telegram_mode)
    if settings.engine_tick_seconds > 0:
        tasks.append(asyncio.create_task(_tick_loop()))
    if settings.live_sim_seconds > 0:
        tasks.append(asyncio.create_task(_live_loop()))
    yield
    for task in tasks:
        task.cancel()


app = FastAPI(title="Riksa Warga API", version="0.2.0", lifespan=lifespan)
for r in (auth, users, regions, reports, stations, incidents, alerts, residents, shelters, context, dashboard,
          tasks, evacuation, routes, integrations, simulation, announcements,
          nature, sar):
    app.include_router(r.router)


@app.get("/health")
def health():
    return {"status": "ok", "telegram_mode": settings.telegram_mode}  # cek cepat: harus "live" agar terkirim ke HP


@app.get("/config")
def public_config():
    """Konfigurasi peta untuk UI (tanpa rahasia)."""
    return {"tile_url": settings.tile_url, "tile_attribution": settings.tile_attribution,
            "routing_enabled": bool(settings.routing_url)}


# UI sederhana (tanpa build). Dipasang terakhir agar rute API di atas diproses lebih dulu.
app.mount("/", StaticFiles(directory=Path(__file__).resolve().parent.parent / "static", html=True), name="ui")
