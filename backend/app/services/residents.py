from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import area_scope_ids
from app.models import FamilyMember, Incident, IncidentStatus, Resident, ResidentStatusLog, SafetyStatus

NEED_HELP = (SafetyStatus.BUTUH_BANTUAN, SafetyStatus.DIDUGA_BUTUH_BANTUAN)


def latest_status_map(db: Session, resident_ids: list[int],
                      incident_id: int | None = None) -> dict[int, ResidentStatusLog]:
    q = select(func.max(ResidentStatusLog.id)).where(ResidentStatusLog.resident_id.in_(resident_ids))
    if incident_id is not None:
        q = q.where(ResidentStatusLog.incident_id == incident_id)
    ids = db.scalars(q.group_by(ResidentStatusLog.resident_id)).all()
    rows = db.scalars(select(ResidentStatusLog).where(ResidentStatusLog.id.in_(ids))).all()
    return {r.resident_id: r for r in rows}


def resident_view(r: Resident, log: ResidentStatusLog | None, *, detail: bool = False, show_last: bool = False) -> dict:
    """show_last=False menyembunyikan lokasi terkini: hanya boleh tampil saat Mode Bencana + izin warga (PRD §5.3)."""
    out = {
        **{c: getattr(r, c) for c in (
            "id", "name", "region_id", "user_id", "address_note", "phone", "has_smartphone",
            "buddy_name", "buddy_phone", "consent", "home_lat", "home_lng")},
        "last_lat": r.last_lat if show_last else None,
        "last_lng": r.last_lng if show_last else None,
        "last_location_at": r.last_location_at if show_last else None,
        "location_consent_at": r.location_consent_at,
        "location_revoked_at": r.location_revoked_at,
        "vulnerability": r.vulnerability or [],
        # tanpa catatan status = belum terkonfirmasi, bukan aman/hilang (PRD §9.2)
        "latest_status": log.status if log else SafetyStatus.BELUM_TERKONFIRMASI,
        "latest_status_at": log.created_at if log else None,
        "latest_status_source": log.source if log else None,
        "latest_need_type": log.need_type if log else None,
    }
    if detail:
        out["assistance_notes"] = r.assistance_notes
    return out


def family_vulnerabilities(db: Session, resident_ids: list[int]) -> dict[int, set[str]]:
    """Kerentanan seluruh anggota keluarga (usia <= 5 = balita, >= 60 = lansia) untuk prioritas evakuasi."""
    out: dict[int, set[str]] = {}
    if not resident_ids:
        return out
    for m in db.scalars(select(FamilyMember).where(FamilyMember.resident_id.in_(resident_ids))):
        s = out.setdefault(m.resident_id, set())
        s.update(m.vulnerability or [])
        if m.age is not None and m.age <= 5:
            s.add("balita")
        if m.age is not None and m.age >= 60:
            s.add("lansia")
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


def help_queue(db: Session, residents: list[Resident], incident_id: int | None) -> list[dict]:
    latest = latest_status_map(db, [r.id for r in residents], incident_id)
    fam = family_vulnerabilities(db, [r.id for r in residents])
    items = []
    for r in residents:
        log = latest.get(r.id)
        if log and log.status in NEED_HELP:
            vulnerable = bool(r.vulnerability) or bool(fam.get(r.id))
            items.append({
                "resident": resident_view(r, log), "is_vulnerable": vulnerable,
                "family_vulnerability": sorted(fam.get(r.id, set())),
                "need_type": log.need_type, "note": log.note, "requested_at": log.created_at, "source": log.source,
                "suspected": log.status == SafetyStatus.DIDUGA_BUTUH_BANTUAN,
            })
    # warga rentan dulu, lalu yang paling lama menunggu
    items.sort(key=lambda i: (not i["is_vulnerable"], i["requested_at"]))
    return items
