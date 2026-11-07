"""Kondisi sungai (3 tingkat), Mode Bencana, izin lokasi, dan "Diduga Butuh Bantuan" (PRD v2 §8-§9)."""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import area_scope_ids
from app.config import settings
from app.models import (
    Alert,
    AlertKind,
    Incident,
    Region,
    RegionLevel,
    Resident,
    ResidentStatusLog,
    RiverLevel,
    RiverStatusLog,
    Role,
    SafetyStatus,
    StatusSource,
    Station,
    User,
)
from app.services import announce
from app.services.geo import haversine_m
from app.services.residents import active_incident_for_region, latest_status_map

# Sudah di jalur bantuan: tidak ditimpa dugaan (permintaan eksplisit warga tidak boleh diturunkan menjadi "diduga").
IN_HELP_PIPELINE = {SafetyStatus.BUTUH_BANTUAN, SafetyStatus.DUGA_BUTUH_BANTUAN, SafetyStatus.DALAM_PENANGANAN,
                    SafetyStatus.DALAM_PERJALANAN}
# Jawaban "aman" hanya berlaku bila diberikan SETELAH bencana dimulai (jawaban lama dari kejadian lain tidak dihitung).
SAFE_ANSWERS = {SafetyStatus.AMAN_MANDIRI, SafetyStatus.AMAN_TERVERIFIKASI, SafetyStatus.TIBA_DI_TITIK_AMAN}


# ---------- kondisi sungai ----------

def latest_condition(db: Session, station_id: int, now: datetime) -> dict | None:
    row = db.scalars(select(RiverStatusLog).where(RiverStatusLog.station_id == station_id)
                     .order_by(RiverStatusLog.id.desc()).limit(1)).first()
    if row is None:
        return None
    age = now - row.created_at
    return {"status": row.status, "set_at": row.created_at, "set_by": row.set_by, "note": row.note,
            "source_mode": row.source_mode, "stale": age > timedelta(hours=settings.condition_stale_hours)}


def _run_start(db: Session, station_id: int, status: RiverLevel) -> datetime | None:
    """Awal rangkaian terakhir kondisi `status` (pembaruan berulang dengan status sama tidak menggeser awal)."""
    rows = db.scalars(select(RiverStatusLog).where(RiverStatusLog.station_id == station_id)
                      .order_by(RiverStatusLog.id.desc())).all()
    start = None
    for r in rows:
        if r.status != status:
            break
        start = r.created_at
    return start


# ---------- Mode Bencana ----------

def area_disaster(db: Session, region_id: int, now: datetime) -> dict:
    """Mode Bencana aktif untuk kelurahan region_id bila ada pos berkondisi Meluap (tidak kedaluwarsa)
    atau pengumuman 'meluap' dalam masa berlaku."""
    area_ids = area_scope_ids(db, region_id)
    reasons, starts, zones = [], [], []
    for st in db.scalars(select(Station).where(Station.region_id.in_(area_ids))):
        cond = latest_condition(db, st.id, now)
        if cond and cond["status"] == RiverLevel.MELUAP and not cond["stale"]:
            reasons.append(f"Sungai meluap di {st.name}")
            starts.append(_run_start(db, st.id, RiverLevel.MELUAP) or cond["set_at"])
            zones.append((st.lat, st.lng))
    ttl = now - timedelta(hours=settings.announcement_ttl_hours)
    for a in db.scalars(select(Alert).where(Alert.kind == AlertKind.PENGUMUMAN, Alert.severity == "meluap",
                                            Alert.audience_region_id.in_(area_ids), Alert.created_at >= ttl)):
        reasons.append(f"Pengumuman pos pantau #{a.id}: sungai meluap")
        starts.append(a.created_at)
    return {"active": bool(reasons), "since": min(starts) if starts else None, "reasons": reasons, "zones": zones}


def live_location_visible(db: Session, region_id: int, now: datetime, cache: dict | None = None) -> bool:
    """Lokasi warga hanya boleh dilihat koordinator/Tim SAR saat Mode Bencana di areanya."""
    key = area_scope_ids(db, region_id) and min(area_scope_ids(db, region_id))
    if cache is not None and key in cache:
        return cache[key]
    active = area_disaster(db, region_id, now)["active"]
    if cache is not None:
        cache[key] = active
    return active


# ---------- izin lokasi ----------

def has_location_consent(r: Resident) -> bool:
    return r.location_consent_at is not None and (r.location_revoked_at is None
                                                  or r.location_revoked_at < r.location_consent_at)


def grant_consent(r: Resident, now: datetime) -> None:
    if not has_location_consent(r):  # izin sekali: tidak diperbarui bila sudah ada
        r.location_consent_at, r.location_revoked_at = now, None


def revoke_consent(r: Resident, now: datetime) -> None:
    r.location_revoked_at = now
    r.last_lat = r.last_lng = r.last_location_at = None  # lokasi terkini dihapus saat izin dicabut


# ---------- Diduga Butuh Bantuan ----------

def _system_user(db: Session) -> int | None:
    return db.scalar(select(User.id).where(User.role == Role.ADMIN, User.is_active.is_(True)).order_by(User.id))


def _in_danger_zone(r: Resident, zones: list[tuple[float, float]], now: datetime) -> bool:
    from app.services.evacuation import resident_location  # impor lokal: hindari siklus
    loc = resident_location(r, now)
    return loc is not None and any(haversine_m(loc[0], loc[1], z[0], z[1]) <= settings.danger_radius_m for z in zones)


def unconfirmed_tick(db: Session, now: datetime) -> list[Alert]:
    """Warga ber-izin-lokasi di zona berbahaya yang tak menjawab dalam N menit sejak Mode Bencana -> Diduga Butuh
    Bantuan. Bukan 'hilang' dan bukan 'aman': hanya masuk antrean Tim SAR/koordinator dengan label dugaan."""
    admin_id = _system_user(db)
    if admin_id is None:
        return []
    fired: list[Alert] = []
    seen: set[int] = set()
    for region in db.scalars(select(Region).where(Region.level == RegionLevel.KELURAHAN)):
        state = area_disaster(db, region.id, now)
        if not state["active"] or state["since"] is None:
            continue
        if now - state["since"] < timedelta(minutes=settings.unconfirmed_minutes):
            continue
        residents = [r for r in db.scalars(select(Resident).where(
            Resident.region_id.in_(area_scope_ids(db, region.id)), Resident.user_id.is_not(None)))
            if r.id not in seen and has_location_consent(r) and _in_danger_zone(r, state["zones"], now)]
        latest = latest_status_map(db, [r.id for r in residents])
        marked = 0
        for r in residents:
            seen.add(r.id)
            log = latest.get(r.id)
            if log and log.status in IN_HELP_PIPELINE:
                continue
            if log and log.status in SAFE_ANSWERS and log.created_at >= state["since"]:
                continue  # sudah menjawab aman sejak bencana dimulai
            incident: Incident | None = active_incident_for_region(db, r.region_id)
            db.add(ResidentStatusLog(
                resident_id=r.id, incident_id=incident.id if incident else None,
                status=SafetyStatus.DUGA_BUTUH_BANTUAN, source=StatusSource.SISTEM,
                note=f"Otomatis: belum menjawab {settings.unconfirmed_minutes} menit di area berbahaya",
                updated_by=admin_id, created_at=now))
            marked += 1
        if marked:
            fired.append(announce.help_alert(db, region.id, region.name, marked, now))
    return fired


def purge_locations(db: Session, now: datetime) -> int:
    """Retensi (FR-056): hapus lokasi terkini yang lebih lama dari batas bila area tidak sedang bencana."""
    cutoff = now - timedelta(hours=settings.location_retention_hours)
    n = 0
    for r in db.scalars(select(Resident).where(Resident.last_location_at.is_not(None),
                                               Resident.last_location_at < cutoff)):
        if not area_disaster(db, r.region_id, now)["active"]:
            r.last_lat = r.last_lng = r.last_location_at = None
            n += 1
    return n
