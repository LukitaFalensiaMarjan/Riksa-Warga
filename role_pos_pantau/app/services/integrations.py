"""Integrasi sumber eksternal. Saat ini: BMKG prakiraan cuaca -> konteks cuaca mesin aturan (FR-013, FR-014, FR-035).

Endpoint: https://api.bmkg.go.id/publik/prakiraan-cuaca?adm4=<kode> (terverifikasi 2026-11-07).
Ini PRAKIRAAN per slot 3 jam, bukan pengamatan. Hasilnya hanya faktor pendukung (PRD FR-035), dan selalu
berlabel prakiraan. Kegagalan sumber hanya mengubah status sumber; data cuaca lama berhenti berlaku sendiri
lewat valid_until, jadi nilai lama tidak dibaca sebagai kondisi sekarang.
"""
import json
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import region_scope_ids
from app.models import Alert, ForecastSlot, IntegrationSource, Role, SourceMode, User, WeatherContext
from app.services import engine

BMKG_URL = "https://api.bmkg.go.id/publik/prakiraan-cuaca?adm4="
SLOT = timedelta(hours=3)
DEFAULT_RAIN_MM = 5.0  # asumsi uji, bukan ambang ilmiah; dapat diubah per sumber (config.rain_mm)
KINDS = ("bmkg",)


def http_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "RiksaWarga/0.2"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read().decode("utf8"))


def parse_slots(payload: dict) -> list[tuple[datetime, dict]]:
    """-> [(waktu UTC naive, entri)] urut waktu. ValueError bila format tidak dikenali."""
    try:
        days = payload["data"][0]["cuaca"]
        slots = [(datetime.strptime(e["datetime"], "%Y-%m-%dT%H:%M:%SZ"), e) for day in days for e in day]
    except (KeyError, IndexError, TypeError, ValueError) as e:
        raise ValueError(f"Format respons BMKG tidak dikenali: {e}")
    if not slots:
        raise ValueError("Respons BMKG kosong")
    return sorted(slots, key=lambda x: x[0])


def current_slot(payload: dict, now: datetime) -> tuple[datetime, dict]:
    """Slot prakiraan terdekat dalam +/- 1,5 jam dari sekarang. BMKG memberi titik waktu per 3 jam (07:00, 10:00, ...),
    jadi pukul 06:54 slot 07:00 yang berlaku; slot yang jauh di masa depan atau sudah lama lewat tidak dipakai."""
    near = [s for s in parse_slots(payload) if abs(s[0] - now) <= SLOT / 2]
    if not near:
        raise ValueError("Tidak ada slot prakiraan yang sedang berlaku")
    return min(near, key=lambda s: abs(s[0] - now))


def _fail(src: IntegrationSource, msg: str) -> list[Alert]:
    src.status, src.last_error = "gagal", msg[:500]
    return []


def sync_source(db: Session, src: IntegrationSource, now: datetime) -> list[Alert]:
    """Tarik satu sumber. Tidak melempar: kegagalan dicatat di status. Pemanggil yang commit."""
    src.last_sync = now
    if src.kind != "bmkg":
        return _fail(src, f"Adapter belum tersedia: {src.kind}")
    cfg = src.config or {}
    region_id, adm4 = cfg.get("region_id"), cfg.get("adm4")
    try:
        if not region_id or not adm4:
            raise ValueError("config wajib berisi region_id dan adm4")
        payload = http_get(BMKG_URL + urllib.parse.quote(str(adm4)))
        slots = parse_slots(payload)
        when, entry = current_slot(payload, now)
        tp = float(entry["tp"])
    except Exception as e:  # sumber eksternal boleh gagal dengan cara apa pun
        return _fail(src, f"{type(e).__name__}: {e}")

    admin_id = db.scalar(select(User.id).where(User.role == Role.ADMIN, User.is_active.is_(True)).order_by(User.id))
    if admin_id is None:
        return _fail(src, "Tidak ada akun admin aktif untuk mencatat pembaruan")
    src.status, src.last_success, src.last_error = "ok", now, None
    store_forecast(db, int(region_id), slots, now, "BMKG prakiraan-cuaca")  # bahan prediksi risiko

    row = db.scalar(select(WeatherContext).where(WeatherContext.region_id == region_id))
    if row is not None and row.source_mode == SourceMode.SIMULATION:
        return []  # konteks cuaca SIMULASI (demo) tidak ditimpa data nyata
    active = tp >= float(cfg.get("rain_mm", DEFAULT_RAIN_MM))
    desc = f"Prakiraan BMKG: curah hujan {tp:g} mm/3 jam (slot {when:%d/%m %H:%M} UTC) — prakiraan, bukan pengamatan"
    old = None if row is None else {"is_active": row.is_active, "description": row.description}
    if row is None:
        row = WeatherContext(region_id=region_id)
        db.add(row)
    row.is_active, row.description, row.source = active, desc[:255], "BMKG prakiraan-cuaca (otomatis)"
    row.source_mode, row.valid_until = SourceMode.REAL, when + SLOT / 2  # titik waktu: berlaku +/- 1,5 jam
    row.updated_by, row.updated_at = admin_id, now
    db.flush()
    log_action(db, actor_id=None, action="weather.sync", entity_type="weather", entity_id=row.id, old=old,
               new={"source": src.name, "is_active": active, "rain_mm": tp})
    return engine.reevaluate_region(db, region_scope_ids(db, region_id), now)


def store_forecast(db: Session, region_id: int, slots: list[tuple[datetime, dict]], now: datetime, source: str) -> None:
    """Simpan slot prakiraan (maks. 48 jam ke depan) per wilayah; upsert per slot."""
    for when, e in slots:
        if when < now - SLOT or when > now + timedelta(hours=48):
            continue
        try:
            mm = float(e.get("tp") or 0)
        except (TypeError, ValueError):
            continue
        row = db.scalar(select(ForecastSlot).where(ForecastSlot.region_id == region_id,
                                                   ForecastSlot.slot_start == when))
        if row is None:
            db.add(ForecastSlot(region_id=region_id, slot_start=when, rain_mm=mm, source=source, fetched_at=now,
                                description=str(e.get("weather_desc") or "")[:80] or None))
        else:
            row.rain_mm, row.fetched_at = mm, now
    db.flush()


def due(src: IntegrationSource, now: datetime) -> bool:
    return src.enabled and (src.last_sync is None
                            or (now - src.last_sync).total_seconds() >= src.poll_interval_seconds)


def sync_due(db: Session, now: datetime) -> list[Alert]:
    fired: list[Alert] = []
    for src in db.scalars(select(IntegrationSource).order_by(IntegrationSource.id)):
        if due(src, now):
            fired += sync_source(db, src, now)
    return fired
