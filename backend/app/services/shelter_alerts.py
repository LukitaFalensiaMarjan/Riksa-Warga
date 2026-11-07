"""Notifikasi shelter penuh/tidak dapat dipakai + rekomendasi alternatif (PRD §6.2, FR-074)."""
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import ancestor_at_level, city_root_id, city_scope_ids
from app.db import utcnow
from app.models import Alert, AlertKind, AlertLevel, RegionLevel, Shelter, ShelterStatus, Station, User, Verification
from app.services.alerting import emit
from app.services.geo import haversine_m
from app.services.messages import FOOTER, fmt_time

AVAILABLE = (ShelterStatus.TERSEDIA, ShelterStatus.TERBATAS)


def alternatives(db: Session, shelter: Shelter, limit: int = 3) -> list[dict]:
    """Shelter terverifikasi yang masih tersedia, terdekat dari shelter ini (bukan shelter itu sendiri)."""
    rows = db.scalars(select(Shelter).where(
        Shelter.id != shelter.id, Shelter.is_verified.is_(True), Shelter.status.in_(AVAILABLE),
        Shelter.region_id.in_(city_scope_ids(db, shelter.region_id)))).all()
    ranked = sorted(((haversine_m(shelter.lat, shelter.lng, s.lat, s.lng), s) for s in rows), key=lambda t: t[0])
    return [{"id": s.id, "name": s.name, "address": s.address, "distance_m": round(d), "status": s.status.value,
             "lat": s.lat, "lng": s.lng} for d, s in ranked[:limit]]


def announce_unavailable(db: Session, shelter: Shelter, actor: User | None, reason: str | None,
                         now: datetime | None = None) -> Alert | None:
    """Beri kabar warga sekitar, Tim SAR, dan pos pantau bahwa shelter penuh/ditutup beserta alternatifnya.
    Dedupe 30 menit per shelter+status agar tidak membanjiri SMS."""
    now = now or utcnow()
    # "warga di sekitar": kelurahan tempat pos pantau terdekat berada; tanpa pos -> seluruh kota
    stations = list(db.scalars(select(Station).where(Station.region_id.in_(city_scope_ids(db, shelter.region_id)))))
    near = min(stations, key=lambda s: haversine_m(shelter.lat, shelter.lng, s.lat, s.lng), default=None)
    audience = (ancestor_at_level(db, near.region_id, RegionLevel.KELURAHAN) if near else None) \
        or city_root_id(db, shelter.region_id)
    word = "PENUH" if shelter.status == ShelterStatus.PENUH else "TIDAK DAPAT DIGUNAKAN"
    alts = alternatives(db, shelter)
    nl = chr(10)
    lines = [f"[RIKSA WARGA — SHELTER {word}]", f"Shelter: {shelter.name}", f"Alamat: {shelter.address}",
             f"Waktu: {fmt_time(now)}", f"Status: {word}" + (f" — {reason.strip()}" if reason else "")]
    if alts:
        lines.append("Alternatif terdekat:")
        lines += [f"- {a['name']} (±{a['distance_m']} m, {a['status']})" for a in alts]
        lines.append("Tindakan: arahkan warga ke shelter alternatif; buka aplikasi untuk rute.")
    else:
        lines.append("Tindakan: belum ada shelter alternatif terverifikasi; ikuti arahan petugas.")
    lines.append(FOOTER)
    return emit(db, kind=AlertKind.SHELTER, level=AlertLevel.WASPADA, verification=Verification.TERVERIFIKASI,
                audience_region_id=audience, message=nl.join(lines), created_by=actor.id if actor else None,
                sms=True, dedupe_key=f"shelter:{shelter.id}:{shelter.status.value}", dedupe_minutes=30, now=now,
                reason=reason, target_roles=["warga", "tim_sar", "pos_pantau", "koordinator"])
