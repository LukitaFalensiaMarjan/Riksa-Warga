"""Pembuatan alert non-kejadian (PRD v2): kondisi sungai, pengumuman pos pantau, shelter penuh, prediksi, bantuan.
Pesan TIDAK memuat nama warga, lokasi, atau data kesehatan (PRD §7.3)."""
from datetime import datetime

from sqlalchemy.orm import Session

from app.auth import ancestor_at_level
from app.models import Alert, AlertKind, RegionLevel, Shelter, ShelterStatus, Station
from app.services.messages import APP, FOOTER, fmt_time
from app.services.geo import haversine_m

SEVERITY_LABEL = {"informasi": "INFORMASI", "waspada": "WASPADA", "meluap": "SUNGAI MELUAP"}
SEVERITY_ACTION = {
    "informasi": "Pantau informasi berikutnya.",
    "waspada": "Waspada: jauhi bantaran dan aliran sungai, siapkan dokumen penting, obat, dan kebutuhan dasar. Pantau pengumuman berikutnya.",
    "meluap": "Bahaya: jika berada di dekat sungai atau area genangan, menjauhlah dan menuju titik aman/shelter terdekat "
              "yang tersedia lewat aplikasi. Bantu tetangga yang rentan bila aman dilakukan.",
}
CONDITION_LABEL = {"normal": "NORMAL", "waspada": "WASPADA", "meluap": "MELUAP"}


def kelurahan_of(db: Session, region_id: int) -> int:
    return ancestor_at_level(db, region_id, RegionLevel.KELURAHAN) or region_id


def _add(db: Session, kind: AlertKind, text: str, *, audience: int, now: datetime, internal: bool = False,
         sms: bool = False, severity: str | None = None, actor_id: int | None = None, reason: str | None = None,
         station_id: int | None = None, parent_id: int | None = None) -> Alert:
    alert = Alert(kind=kind, message=text, audience_region_id=audience, internal=internal, sms=sms, severity=severity,
                  created_by=actor_id, reason=reason, station_id=station_id, parent_id=parent_id, created_at=now)
    db.add(alert)
    db.flush()
    return alert


def condition_alert(db: Session, station: Station, status: str, note: str | None, simulation: bool,
                    actor_id: int, now: datetime) -> Alert:
    """Kondisi sungai berubah (tombol pos pantau). SMS hanya untuk Waspada/Meluap."""
    sim = "[SIMULASI] " if simulation else ""
    lines = [f"{sim}[{APP} — KONDISI SUNGAI: {CONDITION_LABEL[status]}]",
             f"Pos pantau: {station.name}{' (hulu)' if station.is_upstream else ''}" +
             (f" — {station.river_name}" if station.river_name else ""),
             f"Diperbarui {fmt_time(now)} oleh pos pantau."]
    if note:
        lines.append(f"Catatan: {note}")
    lines.append(SEVERITY_ACTION.get(status, "Kondisi kembali normal. Tetap pantau informasi."))
    lines.append(FOOTER)
    return _add(db, AlertKind.KONDISI, "\n".join(lines), audience=kelurahan_of(db, station.region_id), now=now,
                sms=status in ("waspada", "meluap"), severity=status, actor_id=actor_id, station_id=station.id)


def announcement(db: Session, *, severity: str, region_id: int, area: str, summary: str, basis: str,
                 simulation: bool, actor_id: int, now: datetime) -> Alert:
    sim = "[SIMULASI] " if simulation else ""
    text = "\n".join([
        f"{sim}[{APP} — PENGUMUMAN POS PANTAU: {SEVERITY_LABEL[severity]}]",
        f"Wilayah: {area}",
        f"Waktu: {fmt_time(now)}",
        summary,
        f"Dasar: {basis}",
        f"Tindakan: {SEVERITY_ACTION[severity]}",
        "Pengumuman ini dari pos pantau, BUKAN perintah evakuasi resmi. " + FOOTER,
    ])
    return _add(db, AlertKind.PENGUMUMAN, text, audience=region_id, now=now, sms=True, severity=severity,
                actor_id=actor_id)


def correction(db: Session, parent: Alert, reason: str, new_text: str | None, actor_id: int, now: datetime) -> Alert:
    text = "\n".join([f"[{APP} — KOREKSI/PEMBATALAN PENGUMUMAN]",
                      f"Pengumuman #{parent.id} dikoreksi pada {fmt_time(now)}.",
                      f"Alasan: {reason}", *( [new_text] if new_text else ["Abaikan pengumuman sebelumnya."] ), FOOTER])
    return _add(db, AlertKind.KOREKSI, text, audience=parent.audience_region_id, now=now, sms=parent.sms,
                severity=parent.severity, actor_id=actor_id, reason=reason, parent_id=parent.id)


def shelter_alert(db: Session, shelter: Shelter, status: ShelterStatus, alternatives: list[tuple[Shelter, float]],
                  actor_id: int, now: datetime) -> Alert:
    label = {ShelterStatus.PENUH: "PENUH", ShelterStatus.TIDAK_DAPAT_DIGUNAKAN: "TIDAK DAPAT DIGUNAKAN"}[status]
    lines = [f"[{APP} — SHELTER {label}]", f"{shelter.name} ({shelter.address})",
             f"Diperbarui {fmt_time(now)} oleh koordinator."]
    if alternatives:
        lines.append("Alternatif terdekat yang masih tersedia:")
        lines += [f"- {s.name} (~{d / 1000:.1f} km)" for s, d in alternatives[:2]]
    else:
        lines.append("Belum ada shelter alternatif yang tercatat tersedia; hubungi koordinator.")
    lines.append(FOOTER)
    return _add(db, AlertKind.SHELTER, "\n".join(lines), audience=kelurahan_of(db, shelter.region_id), now=now,
                sms=True, actor_id=actor_id)


def nearest_alternatives(shelters: list[Shelter], origin: Shelter) -> list[tuple[Shelter, float]]:
    ok = [s for s in shelters if s.id != origin.id and s.is_verified
          and s.status in (ShelterStatus.TERSEDIA, ShelterStatus.TERBATAS)]
    return sorted(((s, haversine_m(origin.lat, origin.lng, s.lat, s.lng)) for s in ok), key=lambda t: t[1])


def prediction_alert(db: Session, region_id: int, area: str, level: str, reasons: list[str], now: datetime) -> Alert:
    lines = [f"[{APP} — PREDIKSI RISIKO BANJIR: {level.upper()}]", f"Wilayah: {area}", f"Diperbarui {fmt_time(now)}",
             "Ini PERKIRAAN berdasarkan prakiraan hujan dan kondisi sungai, bukan kepastian banjir.",
             *[f"- {r}" for r in reasons[:4]],
             "Bersiaplah: periksa tas siaga, dokumen, obat, dan kenali shelter terdekat di aplikasi.", FOOTER]
    return _add(db, AlertKind.PREDIKSI, "\n".join(lines), audience=region_id, now=now, sms=level == "tinggi",
                severity=level)


def help_alert(db: Session, region_id: int, area: str, count: int, now: datetime) -> Alert:
    text = (f"[{APP} — WARGA DIDUGA BUTUH BANTUAN (INTERNAL)]\nWilayah: {area}\n"
            f"{count} warga ditandai Diduga Butuh Bantuan karena belum menjawab di area berbahaya.\n"
            "Buka aplikasi untuk peta dan prioritas (lokasi tidak dikirim lewat pesan).")
    return _add(db, AlertKind.BANTUAN, text, audience=region_id, now=now, internal=True)
