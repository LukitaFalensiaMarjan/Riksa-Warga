from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import area_scope_ids
from app.models import Incident, IncidentStatus, Resident, ResidentStatusLog, SafetyStatus


def latest_status_map(db: Session, resident_ids: list[int],
                      incident_id: int | None = None) -> dict[int, ResidentStatusLog]:
    q = select(func.max(ResidentStatusLog.id)).where(ResidentStatusLog.resident_id.in_(resident_ids))
    if incident_id is not None:
        q = q.where(ResidentStatusLog.incident_id == incident_id)
    ids = db.scalars(q.group_by(ResidentStatusLog.resident_id)).all()
    rows = db.scalars(select(ResidentStatusLog).where(ResidentStatusLog.id.in_(ids))).all()
    return {r.resident_id: r for r in rows}


def resident_view(r: Resident, log: ResidentStatusLog | None, *, detail: bool = False, hide_live: bool = False) -> dict:
    out = {
        **{c: getattr(r, c) for c in (
            "id", "name", "region_id", "user_id", "household", "address_note", "phone", "has_smartphone",
            "buddy_name", "buddy_phone", "consent", "home_lat", "home_lng", "last_lat", "last_lng",
            "last_location_at")},
        "vulnerability": r.vulnerability or [],
        # tanpa catatan status = belum terkonfirmasi, bukan aman/hilang (PRD §12.2)
        "latest_status": log.status if log else SafetyStatus.BELUM_TERKONFIRMASI,
        "latest_status_at": log.created_at if log else None,
        "latest_status_source": log.source if log else None,
        "latest_need_type": log.need_type if log else None,
    }
    out["location_consent"] = r.location_consent_at is not None and (
        r.location_revoked_at is None or r.location_revoked_at < r.location_consent_at)
    if hide_live:  # lokasi terkini hanya terlihat saat Mode Bencana (PRD v2 §8)
        out["last_lat"] = out["last_lng"] = out["last_location_at"] = None
    if detail:
        out["assistance_notes"] = r.assistance_notes
    return out


def active_incident_for_region(db: Session, region_id: int) -> Incident | None:
    q = (select(Incident).where(Incident.status == IncidentStatus.AKTIF,
                                Incident.region_id.in_(area_scope_ids(db, region_id)))
         .order_by(Incident.started_at.desc(), Incident.id.desc()).limit(1))
    return db.scalars(q).first()


def status_summary(db: Session, residents: list[Resident], incident_id: int | None) -> dict:
    latest = latest_status_map(db, [r.id for r in residents], incident_id)
    counts = {s: 0 for s in SafetyStatus}
    for r in residents:
        log = latest.get(r.id)
        counts[log.status if log else SafetyStatus.BELUM_TERKONFIRMASI] += 1
    return {"incident_id": incident_id, "total": len(residents), "by_status": counts}


def help_queue(db: Session, residents: list[Resident], incident_id: int | None, live_ok=None) -> list[dict]:
    latest = latest_status_map(db, [r.id for r in residents], incident_id)
    items = []
    for r in residents:
        log = latest.get(r.id)
        if log and log.status in (SafetyStatus.BUTUH_BANTUAN, SafetyStatus.DUGA_BUTUH_BANTUAN):
            items.append({
                "resident": resident_view(r, log, hide_live=live_ok is not None and not live_ok(r)), "is_vulnerable": bool(r.vulnerability),
                "need_type": log.need_type, "note": log.note, "requested_at": log.created_at, "source": log.source,
            })
    # warga rentan dulu, lalu yang paling lama menunggu
    items.sort(key=lambda i: (not i["is_vulnerable"], i["requested_at"]))
    return items
