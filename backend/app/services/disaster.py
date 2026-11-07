"""Mode Bencana, zona berbahaya, dan aturan "Diduga Butuh Bantuan" (PRD §8 dan §9).

Semua ambang adalah asumsi uji (D-02, D-06, D-10) dan bisa diubah lewat .env.

- Mode Bencana aktif untuk suatu area bila (a) ada pos berstatus MELUAP di area itu, atau (b) ada pengumuman
  Waspada/Siaga/Evakuasi (belum dibatalkan) untuk area itu dalam `mode_hours` terakhir.
- Zona berbahaya = lingkaran `hazard_radius_m` di sekitar pos berstatus MELUAP + titik kejadian berlevel
  Siaga/Evakuasi. Penetapan polygon resmi menunggu data BPBD (D-02).
- Lokasi terakhir warga hanya dipakai/dilihat pihak lain saat Mode Bencana aktif DAN warga memberi izin.
"""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import area_scope_ids, region_scope_ids
from app.config import settings
from app.db import utcnow
from app.models import (
    Alert,
    AlertKind,
    AlertLevel,
    Incident,
    IncidentStatus,
    Region,
    Resident,
    ResidentStatusLog,
    SafetyStatus,
    StatusSource,
    Station,
)
from app.services.alerting import emit
from app.services.geo import haversine_m

LOCATION_FRESH = timedelta(hours=6)  # lokasi terkini lebih tua dari ini tidak dianggap posisi sekarang
MODE_LEVELS = (AlertLevel.WASPADA, AlertLevel.SIAGA, AlertLevel.EVAKUASI)
INCIDENT_ZONE_M = {"banjir": 300, "kebakaran": 150, "lainnya": 100}


def meluap_stations(db: Session) -> list[Station]:
    return list(db.scalars(select(Station).where(Station.condition == "meluap")))


def mode_regions(db: Session, now: datetime | None = None) -> dict[int, datetime]:
    """region_id -> waktu Mode Bencana mulai di area itu (yang paling awal)."""
    now = now or utcnow()
    out: dict[int, datetime] = {}

    def add(ids: set[int], since: datetime) -> None:
        for rid in ids:
            if rid not in out or since < out[rid]:
                out[rid] = since

    for s in meluap_stations(db):
        add(area_scope_ids(db, s.region_id), s.condition_at or now)

    cutoff = now - timedelta(hours=settings.mode_hours)
    announcements = db.scalars(select(Alert).where(
        Alert.created_at >= cutoff, Alert.internal.is_(False),
        Alert.kind.in_([AlertKind.PENGUMUMAN, AlertKind.LEVEL]), Alert.level.in_(MODE_LEVELS))).all()
    cancelled = set(db.scalars(select(Alert.parent_alert_id).where(
        Alert.kind == AlertKind.PEMBATALAN, Alert.parent_alert_id.is_not(None))))
    for a in announcements:
        if a.id in cancelled:
            continue
        inc = db.get(Incident, a.incident_id) if a.incident_id else None
        if inc is not None and inc.status != IncidentStatus.AKTIF:
            continue  # kejadian sudah ditutup/dibatalkan
        add(region_scope_ids(db, a.audience_region_id), a.created_at)
    return out


def hazard_zones(db: Session) -> list[dict]:
    zones = [{"lat": s.lat, "lng": s.lng, "radius_m": settings.hazard_radius_m, "kind": "sungai",
              "label": f"Luapan {s.river_name or s.name} ({s.name})", "ref": s.id} for s in meluap_stations(db)]
    for i in db.scalars(select(Incident).where(
            Incident.status == IncidentStatus.AKTIF, Incident.level.in_([AlertLevel.SIAGA, AlertLevel.EVAKUASI]))):
        zones.append({"lat": i.lat, "lng": i.lng, "radius_m": INCIDENT_ZONE_M.get(i.hazard.value, 200),
                      "kind": "kejadian", "label": f"Kejadian #{i.id} {i.hazard.value}", "ref": i.id})
    return zones


def in_hazard(lat: float | None, lng: float | None, zones: list[dict]) -> bool:
    if lat is None or lng is None:
        return False
    return any(haversine_m(lat, lng, z["lat"], z["lng"]) <= z["radius_m"] for z in zones)


def last_location_usable(r: Resident, mode: dict[int, datetime], now: datetime) -> bool:
    """Lokasi terkini boleh dipakai pihak lain: izin ada & tidak dicabut, Mode Bencana aktif, data segar."""
    return bool(r.location_consented and r.region_id in mode and r.last_lat is not None
                and r.last_location_at and now - r.last_location_at <= LOCATION_FRESH)


def apply_diduga(db: Session, now: datetime | None = None) -> list[Alert]:
    """Warga berizin lokasi, di zona berbahaya, tak menjawab `diduga_minutes` sejak Mode Bencana -> Diduga Butuh Bantuan."""
    now = now or utcnow()
    mode = mode_regions(db, now)
    zones = hazard_zones(db) if mode else []
    if not mode or not zones:
        return []
    alerts: list[Alert] = []
    residents = db.scalars(select(Resident).where(
        Resident.region_id.in_(list(mode)), Resident.location_consent_at.is_not(None),
        Resident.location_revoked_at.is_(None), Resident.last_lat.is_not(None))).all()
    for r in residents:
        since = mode[r.region_id]
        if now - since < timedelta(minutes=settings.diduga_minutes) or not last_location_usable(r, mode, now):
            continue
        if not in_hazard(r.last_lat, r.last_lng, zones):
            continue  # di luar area berbahaya: tidak otomatis dianggap butuh bantuan (PRD §17.2)
        latest = db.scalars(select(ResidentStatusLog).where(ResidentStatusLog.resident_id == r.id)
                            .order_by(ResidentStatusLog.id.desc()).limit(1)).first()
        if latest is not None and latest.created_at >= since:
            continue  # sudah menjawab, atau sudah ditandai dugaan sejak mode ini
        db.add(ResidentStatusLog(
            resident_id=r.id, status=SafetyStatus.DIDUGA_BUTUH_BANTUAN, source=StatusSource.SISTEM,
            note=f"Tidak menjawab {settings.diduga_minutes} menit sejak Mode Bencana, lokasi di area berbahaya",
            lat=r.last_lat, lng=r.last_lng, updated_by=None, created_at=now))
        region = db.get(Region, r.region_id)
        a = emit(
            db, kind=AlertKind.BANTUAN, internal=True, audience_region_id=r.region_id, now=now,
            target_roles=["koordinator", "tim_sar"], dedupe_key=f"diduga:{r.id}:{since.isoformat()}", dedupe_minutes=1440,
            message=(f"[RIKSA WARGA — DIDUGA BUTUH BANTUAN]\nWilayah: {region.name if region else '-'}\n"
                     f"Seorang warga tidak menjawab {settings.diduga_minutes} menit dan lokasinya di area berbahaya. "
                     "Ini dugaan, bukan konfirmasi. Buka aplikasi untuk detail, prioritas, dan peta."))
        if a is not None:
            alerts.append(a)
    return alerts


def purge_old_locations(db: Session, now: datetime | None = None) -> int:
    """Retensi lokasi (FR-056): hapus lokasi terakhir yang lebih tua dari `location_retention_hours`."""
    now = now or utcnow()
    cutoff = now - timedelta(hours=settings.location_retention_hours)
    rows = db.scalars(select(Resident).where(Resident.last_location_at.is_not(None),
                                             Resident.last_location_at < cutoff)).all()
    for r in rows:
        r.last_lat = r.last_lng = r.last_location_at = None
    return len(rows)
