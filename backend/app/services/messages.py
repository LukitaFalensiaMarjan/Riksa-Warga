"""Template pesan alert. Hanya memakai data kejadian/wilayah — data warga rentan tidak pernah masuk ke sini."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import region_scope_ids
from app.models import (
    AlertKind,
    AlertLevel,
    Hazard,
    Incident,
    Observation,
    Region,
    Report,
    ReportSource,
    Shelter,
    ShelterStatus,
    Station,
    Verification,
)

APP = "RIKSA WARGA"
WIB = timezone(timedelta(hours=7))
FOOTER = "Ikuti arahan koordinator dan petugas berwenang (BPBD/Damkar/SAR). Darurat: 112."

HAZARD = {Hazard.BANJIR: "BANJIR", Hazard.KEBAKARAN: "KEBAKARAN"}
VERIF = {Verification.BELUM: "BELUM DIVERIFIKASI", Verification.TERVERIFIKASI: "TERVERIFIKASI"}
SOURCE = {
    ReportSource.WARGA: "laporan warga",
    ReportSource.POS_PANTAU: "pos pantau",
    ReportSource.SENSOR: "sensor",
    ReportSource.KOORDINATOR: "koordinator",
}
NOT_EVAC = "Status ini BUKAN perintah evakuasi."
ACTIONS = {
    (Hazard.BANJIR, AlertLevel.PANTAU): "Tetap tenang dan pantau informasi berikutnya.",
    (Hazard.BANJIR, AlertLevel.WASPADA): (
        "Pantau informasi, jauhi aliran sungai dan saluran air, siapkan dokumen penting, obat, "
        "dan kebutuhan dasar."),
    (Hazard.BANJIR, AlertLevel.SIAGA): (
        "Bersiap untuk kemungkinan evakuasi: amankan dokumen dan obat, bantu tetangga rentan bila aman "
        f"dilakukan. {NOT_EVAC}"),
    (Hazard.BANJIR, AlertLevel.EVAKUASI): (
        "Segera menuju titik aman mengikuti arahan petugas. Jangan berjalan atau berkendara melewati arus air."),
    (Hazard.KEBAKARAN, AlertLevel.PANTAU): "Tetap tenang, jangan mendekati lokasi, pantau informasi berikutnya.",
    (Hazard.KEBAKARAN, AlertLevel.WASPADA): (
        "Jauhi area kejadian, jangan mendekati sumber api atau kabel listrik, beri jalan untuk Damkar."),
    (Hazard.KEBAKARAN, AlertLevel.SIAGA): (
        "Jauhi area kejadian, jangan mendekati sumber api atau kabel listrik, jangan mencoba memadamkan api "
        f"besar sendiri, beri jalan untuk Damkar. {NOT_EVAC}"),
    (Hazard.KEBAKARAN, AlertLevel.EVAKUASI): (
        "Segera tinggalkan area ke arah yang menjauhi api dan asap menuju titik aman. Jangan kembali masuk "
        "ke bangunan. Ikuti arahan Damkar/petugas."),
}


def fmt_time(dt: datetime) -> str:
    return dt.replace(tzinfo=timezone.utc).astimezone(WIB).strftime("%d-%m-%Y %H:%M WIB")


def _title(incident: Incident, label: str) -> str:
    prefix = "[SIMULASI] " if incident.is_simulation else ""
    return f"{prefix}[{APP} — {label}]"


def _region_name(db: Session, region_id: int) -> str:
    region = db.get(Region, region_id)
    return region.name if region else "-"


def _sources(db: Session, incident: Incident) -> str:
    rows = db.scalars(select(Report.source).where(Report.incident_id == incident.id).distinct()).all()
    return ", ".join(sorted(SOURCE[s] for s in rows)) or "-"


def _shelters(db: Session, area_region_id: int) -> str:
    rows = db.scalars(select(Shelter).where(
        Shelter.region_id.in_(region_scope_ids(db, area_region_id)),
        Shelter.is_verified.is_(True),
        Shelter.status.in_([ShelterStatus.TERSEDIA, ShelterStatus.TERBATAS]),
    ).order_by(Shelter.id)).all()
    return "; ".join(f"{s.name} ({s.status.value})" for s in rows)


def _header(db: Session, incident: Incident, title: str, audience_region_id: int, now: datetime) -> list[str]:
    return [
        title,
        f"ID Kejadian: #{incident.id}",
        f"Wilayah: {_region_name(db, audience_region_id)} (lokasi laporan: {_region_name(db, incident.region_id)})",
        f"Waktu pembaruan: {fmt_time(now)}",
    ]


def level_message(db: Session, incident: Incident, kind: AlertKind, old_level: AlertLevel,
                  audience_region_id: int, reason: str | None, now: datetime) -> str:
    hz, lvl = HAZARD[incident.hazard], incident.level.value.upper()
    label = f"KOREKSI {hz}" if kind == AlertKind.KOREKSI else f"{lvl} {hz}"
    change = "diturunkan" if kind == AlertKind.KOREKSI else "dinaikkan"
    lines = _header(db, incident, _title(incident, label), audience_region_id, now) + [
        f"Status: {lvl} — {VERIF[incident.verification]}",
        "",
        f"Level {change} dari {old_level.value.upper()} ke {lvl}.",
        f"Ringkasan: {incident.unique_reporters} pelapor independen sejak {fmt_time(incident.started_at)}.",
        f"Tindakan: {ACTIONS[(incident.hazard, incident.level)]}",
    ]
    if incident.level == AlertLevel.EVAKUASI:
        lines.append(f"Titik aman terverifikasi: {_shelters(db, audience_region_id) or 'tanyakan ke koordinator/posko'}")
    if reason:
        lines.append(f"Alasan: {reason}")
    lines += [f"Sumber: {_sources(db, incident)}", FOOTER]
    return "\n".join(lines)


def cancel_message(db: Session, incident: Incident, audience_region_id: int, reason: str, now: datetime) -> str:
    lines = _header(db, incident, _title(incident, "PEMBATALAN PERINGATAN"), audience_region_id, now) + [
        "",
        f"Peringatan {HAZARD[incident.hazard]} untuk kejadian #{incident.id} DIBATALKAN.",
        f"Alasan: {reason}",
        "Abaikan peringatan sebelumnya untuk kejadian ini. Tetap waspada terhadap informasi resmi.",
        FOOTER,
    ]
    return "\n".join(lines)


def close_message(db: Session, incident: Incident, audience_region_id: int, reason: str, now: datetime) -> str:
    lines = _header(db, incident, _title(incident, "TERKENDALI/SELESAI"), audience_region_id, now) + [
        "",
        f"Kejadian {HAZARD[incident.hazard]} #{incident.id} dinyatakan terkendali/selesai.",
        f"Catatan: {reason}",
        FOOTER,
    ]
    return "\n".join(lines)


def pantau_message(db: Session, incident: Incident, now: datetime) -> str:
    lines = _header(db, incident, _title(incident, f"PANTAU {HAZARD[incident.hazard]} (INTERNAL)"),
                    incident.region_id, now) + [
        f"Status: PANTAU — {VERIF[incident.verification]}",
        "Laporan baru masuk dan perlu ditinjau koordinator. Belum ada peringatan ke warga.",
        f"Sumber: {_sources(db, incident)}",
    ]
    return "\n".join(lines)


def proposal_message(db: Session, incident: Incident, timeout_minutes: int, now: datetime) -> str:
    lines = _header(db, incident, _title(incident, f"USULAN WASPADA {HAZARD[incident.hazard]} (INTERNAL)"),
                    incident.region_id, now) + [
        f"{incident.unique_reporters} pelapor unik memenuhi aturan Waspada.",
        f"Konfirmasi atau tolak dalam {timeout_minutes} menit. Tanpa respons, Waspada dikirim otomatis "
        "dengan label BELUM DIVERIFIKASI.",
        f"Sumber: {_sources(db, incident)}",
    ]
    return "\n".join(lines)


def risk_message(station: Station, obs: Observation, label: str, threshold: float) -> str:
    sim = "[SIMULASI] " if obs.source_mode.value == "simulation" else ""
    return "\n".join([
        f"{sim}[{APP} — STATUS RISIKO BANJIR (INTERNAL)]",
        f"Pos pantau: {station.name}{' (hulu)' if station.is_upstream else ''}",
        f"Tinggi air {obs.level_cm:.0f} cm pada {fmt_time(obs.observed_at)}, melewati ambang {label} {threshold:.0f} cm.",
        f"Kondisi sungai: {obs.river_condition.value}",
        "Ini status risiko, bukan konfirmasi banjir telah terjadi. Periksa laporan lapangan.",
    ])
