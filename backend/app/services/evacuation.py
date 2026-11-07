"""Prioritas evakuasi warga. Skor transparan = alat bantu urutan pemeriksaan, bukan keputusan (PRD §7.2)."""
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models import (
    AlertLevel,
    Incident,
    NeedType,
    RescueTask,
    Resident,
    ResidentStatusLog,
    SafetyStatus,
    Shelter,
    ShelterStatus,
)
from app.services.geo import haversine_m
from app.services.disaster import hazard_zones, in_hazard, last_location_usable
from app.services.residents import family_vulnerabilities, latest_status_map

LOCATION_FRESH = timedelta(hours=6)  # lokasi terkini lebih lama dari ini -> pakai lokasi rumah
SAFE = {SafetyStatus.AMAN_TERVERIFIKASI, SafetyStatus.TIBA_DI_TITIK_AMAN}
STATUS_POINTS = {
    SafetyStatus.BUTUH_BANTUAN: (40, "Meminta bantuan"),
    SafetyStatus.DIDUGA_BUTUH_BANTUAN: (35, "Diduga butuh bantuan (tak menjawab di area berbahaya)"),
    SafetyStatus.TIDAK_DAPAT_DIHUBUNGI: (30, "Tidak dapat dihubungi"),
    SafetyStatus.BELUM_TERKONFIRMASI: (20, "Belum ada kabar"),
    SafetyStatus.DALAM_PENANGANAN: (10, "Sedang ditangani"),
    SafetyStatus.DALAM_PERJALANAN: (5, "Dalam perjalanan ke titik aman"),
    SafetyStatus.AMAN_MANDIRI: (5, "Aman (laporan mandiri, belum diverifikasi)"),
}
VULN_POINTS = {"disabilitas": 20, "balita": 18, "sakit": 15, "lansia": 15, "hamil": 12, "anak": 10,
               "tinggal_sendiri": 8, "lainnya": 5}
FAMILY_CAP = 20
VULN_CAP = 35
NEED_POINTS = {NeedType.MEDIS: 15, NeedType.EVAKUASI: 10}
LEVEL_POINTS = {AlertLevel.EVAKUASI: 15, AlertLevel.SIAGA: 10, AlertLevel.WASPADA: 5}
LABELS = ((70, "kritis"), (45, "tinggi"), (25, "sedang"), (0, "rendah"))
AVAILABLE = (ShelterStatus.TERSEDIA, ShelterStatus.TERBATAS)


def resident_location(r: Resident, now: datetime, allow_last: bool = False) -> tuple[float, float, str] | None:
    """Lokasi terkini hanya dipakai bila allow_last (Mode Bencana + izin warga); selain itu lokasi rumah."""
    if allow_last and r.last_lat is not None and r.last_location_at and now - r.last_location_at <= LOCATION_FRESH:
        return r.last_lat, r.last_lng, "terkini"
    if r.home_lat is not None:
        return r.home_lat, r.home_lng, "rumah"
    return None


def priority_label(score: int) -> str:
    return next(name for floor, name in LABELS if score >= floor)


def nearest_shelter(shelters: list[Shelter], lat: float, lng: float) -> tuple[Shelter, float] | None:
    usable = [s for s in shelters if s.is_verified and s.status in AVAILABLE]
    return min(((s, haversine_m(lat, lng, s.lat, s.lng)) for s in usable), key=lambda t: t[1], default=None)


def score_resident(r: Resident, log: ResidentStatusLog | None, incident: Incident | None, now: datetime,
                   family: set[str] | None = None, allow_last: bool = False,
                   zones: list[dict] | None = None) -> tuple[int, list[dict], tuple | None]:
    factors: list[dict] = []

    def add(name: str, points: int, note: str) -> None:
        factors.append({"faktor": name, "poin": points, "keterangan": note})

    status = log.status if log else SafetyStatus.BELUM_TERKONFIRMASI
    points, note = STATUS_POINTS.get(status, (0, status.value))
    add("status", points, note)
    vuln = [v for v in (r.vulnerability or []) if v in VULN_POINTS]
    if vuln:
        add("kerentanan", min(sum(VULN_POINTS[v] for v in vuln), VULN_CAP), ", ".join(vuln))
    extra = sorted((family or set()) - set(vuln))
    if extra:
        add("keluarga_rentan", min(sum(VULN_POINTS.get(v, 5) for v in extra), FAMILY_CAP),
            "Anggota keluarga: " + ", ".join(extra))
    if not r.has_smartphone:
        add("tanpa_smartphone", 10, "Tidak punya smartphone, perlu dicek langsung")
    if status == SafetyStatus.BUTUH_BANTUAN and log and log.need_type in NEED_POINTS:
        add("kebutuhan", NEED_POINTS[log.need_type], f"Butuh {log.need_type.value}")
    if status == SafetyStatus.BUTUH_BANTUAN and log:
        waited = int((now - log.created_at).total_seconds() // 60)
        if waited >= 5:
            add("lama_menunggu", min(waited // 5, 15), f"Menunggu {waited} menit")
    loc = resident_location(r, now, allow_last)
    if loc is not None and in_hazard(loc[0], loc[1], zones or []):
        add("area_berbahaya", 15, "Lokasi berada di area berbahaya")
    if loc is None:
        add("lokasi_tidak_diketahui", 5, "Lokasi belum ada, cek manual")
    elif incident is not None:
        d = haversine_m(loc[0], loc[1], incident.lat, incident.lng)
        if d <= 300:
            add("dekat_kejadian", 20, f"{d:.0f} m dari titik kejadian")
        elif d <= 1000:
            add("dekat_kejadian", 10, f"{d:.0f} m dari titik kejadian")
    if incident is not None and incident.level in LEVEL_POINTS:
        add("level_kejadian", LEVEL_POINTS[incident.level], f"Kejadian #{incident.id} level {incident.level.value}")
    return sum(f["poin"] for f in factors), factors, loc


def priorities(db: Session, residents: list[Resident], incident: Incident | None, shelters: list[Shelter],
               tasks: list[RescueTask], now: datetime, mode: dict | None = None) -> list[dict]:
    """mode = hasil disaster.mode_regions; lokasi terkini hanya dipakai pada area ber-Mode Bencana (PRD §8)."""
    latest = latest_status_map(db, [r.id for r in residents], incident.id if incident else None)
    fam = family_vulnerabilities(db, [r.id for r in residents])
    zones = hazard_zones(db)
    mode = mode or {}
    task_by_resident = {t.resident_id: t for t in sorted(tasks, key=lambda t: t.id)}  # tugas aktif terbaru
    out = []
    for r in residents:
        log = latest.get(r.id)
        status = log.status if log else SafetyStatus.BELUM_TERKONFIRMASI
        if status in SAFE:
            continue
        allow_last = last_location_usable(r, mode, now)
        score, factors, loc = score_resident(r, log, incident, now, fam.get(r.id), allow_last, zones)
        near = nearest_shelter(shelters, loc[0], loc[1]) if loc else None
        task = task_by_resident.get(r.id)
        out.append({
            "resident_id": r.id, "name": r.name, "region_id": r.region_id, "vulnerability": r.vulnerability or [],
            "has_smartphone": r.has_smartphone, "status": status.value, "family_vulnerability": sorted(fam.get(r.id, set())),
            "in_hazard_zone": loc is not None and in_hazard(loc[0], loc[1], zones),
            "need_type": log.need_type.value if log and log.need_type else None,
            "status_at": log.created_at if log else None, "score": score, "priority": priority_label(score),
            "factors": factors, "lat": loc[0] if loc else None, "lng": loc[1] if loc else None,
            "location_source": loc[2] if loc else None,
            "nearest_shelter": {"id": near[0].id, "name": near[0].name, "distance_m": round(near[1])} if near else None,
            "task": {"id": task.id, "status": task.status.value, "assignee_id": task.assignee_id} if task else None,
        })
    out.sort(key=lambda x: (-x["score"], x["name"]))
    return out
