"""Panel pencocokan laporan warga dengan data sungai dan hujan (PRD §7.2, FR-025).

ALAT BANTU keputusan pos pantau, bukan bukti mutlak. Laporan tidak pernah dihapus karena hasilnya "tidak sesuai".
"""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models import Hazard, Incident, Observation, Report, Station
from app.services import forecast
from app.services.engine import REVIEW_FLAGS
from app.services.geo import haversine_m

NEAR_STATION_M = 3000  # asumsi uji
RAIN_SUPPORT_MM = 5.0


def _check(key: str, label: str, status: str, detail: str) -> dict:
    return {"key": key, "label": label, "status": status, "detail": detail}


def match_report(db: Session, report: Report, now: datetime) -> dict:
    if report.hazard != Hazard.BANJIR:
        return {"report_id": report.id, "result": "data_kurang", "checks": [], "ok": 0, "no": 0,
                "note": "Laporan jenis lain hanya informasi: tidak dicocokkan dengan data banjir.", "station": None}
    checks: list[dict] = []
    stations = list(db.scalars(select(Station)))
    nearest = min(stations, key=lambda s: haversine_m(report.lat, report.lng, s.lat, s.lng), default=None)

    if nearest is None:
        checks.append(_check("jarak", "Jarak ke pos/sungai", "unknown", "Belum ada pos pantau"))
        checks.append(_check("sungai", "Kondisi sungai", "unknown", "Belum ada data"))
    else:
        d = haversine_m(report.lat, report.lng, nearest.lat, nearest.lng)
        checks.append(_check("jarak", "Jarak ke pos/sungai", "ok" if d <= NEAR_STATION_M else "no",
                             f"{nearest.name} ({nearest.river_name or 'sungai'}) ±{d:.0f} m dari lokasi laporan"))
        hours = settings.condition_stale_hours
        cond_fresh = bool(nearest.condition_at and now - nearest.condition_at < timedelta(hours=hours))
        obs = db.scalars(select(Observation).where(Observation.station_id == nearest.id)
                         .order_by(Observation.observed_at.desc(), Observation.id.desc()).limit(1)).first()
        level_txt = ""
        if obs:
            sim = " (simulasi)" if obs.source_mode.value == "simulation" else ""
            level_txt = f", tinggi air terakhir {obs.level_cm:.0f} cm{sim}"
        if not cond_fresh:
            checks.append(_check("sungai", "Kondisi sungai (pos pantau)", "unknown",
                                 f"Belum diperbarui pos pantau dalam {hours} jam{level_txt}"))
        elif (nearest.condition or "normal") in ("waspada", "meluap"):
            checks.append(_check("sungai", "Kondisi sungai (pos pantau)", "ok",
                                 f"Sungai {nearest.condition.upper()} — sesuai laporan banjir{level_txt}"))
        else:
            checks.append(_check("sungai", "Kondisi sungai (pos pantau)", "no",
                                 f"Sungai NORMAL — tidak sesuai laporan banjir{level_txt}. Bisa genangan lokal/drainase."))

    recent = forecast.rain_recent_mm(now)
    if recent is None:
        checks.append(_check("hujan", "Data hujan", "unknown", "Data hujan tidak tersedia (sumber gagal diakses)"))
    elif recent >= RAIN_SUPPORT_MM:
        checks.append(_check("hujan", "Data hujan", "ok", f"Hujan {recent} mm dalam ±4 jam (model prakiraan) — mendukung"))
    elif recent < 1.0:
        checks.append(_check("hujan", "Data hujan", "no", f"Hampir tidak ada hujan ({recent} mm) — kurang mendukung"))
    else:
        checks.append(_check("hujan", "Data hujan", "unknown", f"Hujan ringan {recent} mm — belum cukup menjadi dasar"))

    unique = 1
    if report.incident_id:
        inc = db.get(Incident, report.incident_id)
        unique = max(1, inc.unique_reporters if inc else 1)
    checks.append(_check("pelapor", "Pelapor unik di area yang sama", "ok" if unique >= 2 else "unknown",
                         f"{unique} pelapor independen"))
    bad = sorted(set(report.flags or []) & REVIEW_FLAGS)
    checks.append(_check("tanda", "Tanda periksa", "no" if bad else "ok",
                         ", ".join(f.replace("_", " ") for f in bad) if bad else "Bersih (tidak duplikat / lokasi cocok)"))

    ok = sum(c["status"] == "ok" for c in checks)
    no = sum(c["status"] == "no" for c in checks)
    core_unknown = sum(c["status"] == "unknown" for c in checks if c["key"] in ("sungai", "hujan"))
    if core_unknown >= 2:
        result = "data_kurang"
    elif no == 0 and ok >= 3:
        result = "sesuai"
    elif ok > no:
        result = "sebagian"
    else:
        result = "tidak_sesuai"
    return {"report_id": report.id, "result": result, "checks": checks, "ok": ok, "no": no,
            "station": {"id": nearest.id, "name": nearest.name} if nearest else None,
            "note": "Alat bantu keputusan, bukan bukti. Laporan tetap tersimpan apa pun hasilnya."}
