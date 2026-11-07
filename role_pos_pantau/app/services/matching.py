"""Pencocokan laporan warga dengan data sungai dan hujan (PRD v2 §7.2).

Membantu keputusan pos pantau, bukan menggantikannya. Hasil: sesuai | sebagian | tidak_sesuai | data_kurang.
Penentu utama = data pos pantau (kondisi + tinggi air) dan kondisi air yang dilaporkan. Hujan hanya pendukung:
banjir kiriman dari hulu bisa terjadi walau di kota tidak hujan."""
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import area_scope_ids
from app.models import ForecastSlot, Incident, Report, ReportStatus, RiverLevel, Station
from app.services import engine, weather_live
from app.services.disaster import latest_condition
from app.services.geo import haversine_m
from app.services.monitoring import is_stale, latest_observation, level_status

NEAR_STATION_M = 5000  # asumsi uji: laporan "dekat" pos bila <= 5 km
LIVE_RAIN_MM_H = 1.0  # asumsi uji: hujan terkini >= 1 mm/jam dianggap hujan
REPORT_RAISED = {"air_naik", "arus_deras", "genangan", "meluap", "masuk_rumah"}  # kondisi air dilaporkan "naik"
REPORT_LABEL = {"normal": "Normal", "air_naik": "Air sungai naik", "arus_deras": "Arus deras", "genangan": "Genangan",
                "meluap": "Sungai meluap", "masuk_rumah": "Air masuk rumah", "surut": "Air mulai surut"}


def match_report(db: Session, report: Report, now: datetime) -> dict:
    checks: list[dict] = []

    def add(name: str, result: str, detail: str) -> None:
        checks.append({"pemeriksaan": name, "hasil": result, "keterangan": detail})  # ok | tidak | kurang

    # 1. kondisi sungai terdekat (kondisi pos + pengamatan tinggi air)
    if report.station is not None:  # area pos pantau dipilih pelapor: cocokkan dengan pos itu
        stations = [report.station]
    else:
        stations = list(db.scalars(select(Station).where(Station.region_id.in_(area_scope_ids(db, report.region_id)))))
    near = sorted(((s, haversine_m(report.lat, report.lng, s.lat, s.lng)) for s in stations), key=lambda t: t[1])
    # laporan tanpa kategori kondisi = laporan banjir biasa (air naik)
    said_up = report.water_condition in REPORT_RAISED if report.water_condition else True
    said = REPORT_LABEL.get(report.water_condition, "banjir (tanpa kategori)") if report.water_condition \
        else "banjir (tanpa kategori)"
    raised = None  # pos naik (waspada/meluap)? None = data pos tidak bisa dipakai
    if not near:
        add("sungai", "kurang", "Tidak ada pos pantau di area laporan")
    else:
        st, dist = near[0]
        obs = latest_observation(db, st.id)
        status = level_status(st, obs, now)
        where = f"{st.name} ({dist:.0f} m{', area dipilih pelapor' if report.station is not None else ''})"
        if status in ("normal", "waspada", "bahaya"):  # utama: angka tinggi air live, tanpa menunggu tombol kondisi
            raised = status != "normal"
            txt = (f"{where}: tinggi air {obs.level_cm:g} cm = {'meluap' if status == 'bahaya' else status} "
                   f"(waspada ≥{st.warning_cm:g}, bahaya ≥{st.danger_cm:g} cm)")
        else:  # cadangan: kondisi yang diatur pos bila belum ada angka tinggi air yang segar
            cond = latest_condition(db, st.id, now)
            if cond is not None and not cond["stale"]:
                raised = cond["status"] != RiverLevel.NORMAL
                txt = f"{where}: belum ada angka tinggi air segar, memakai kondisi pos {cond['status'].value}"
            else:
                txt = f"{where}: data tinggi air kedaluwarsa/belum ada"
        if report.station is None and dist > NEAR_STATION_M:
            add("sungai", "kurang", txt + " — pos terlalu jauh dari lokasi laporan")
            raised = None
        elif raised is None:
            add("sungai", "kurang", txt)
        else:
            same = said_up == raised
            add("sungai", "ok" if same else "tidak",
                f"{txt}. Dilaporkan \"{said}\" — {'sejalan' if same else 'tidak sejalan'}")

    # 2. hujan (pendukung): Open-Meteo terkini + prakiraan BMKG slot berjalan + konteks cuaca aktif
    near = list(db.scalars(select(ForecastSlot).where(
        ForecastSlot.region_id.in_(area_scope_ids(db, report.region_id)),
        ForecastSlot.slot_start >= now - timedelta(hours=1.5), ForecastSlot.slot_start <= now + timedelta(hours=1.5))))
    slot = min(near, key=lambda s: abs(s.slot_start - now)) if near else None  # titik waktu terdekat (+/- 1,5 jam)
    weather = engine.weather_active(db, report.region_id, now, engine.SourceMode.REAL)
    live = weather_live.current()
    live_rain = live.get("rain_mm_per_hour") if live.get("status") == "ok" else None
    if slot is None and not weather and live_rain is None:
        add("hujan", "kurang", "Tidak ada data hujan yang masih berlaku (pendukung)")
    else:
        rain = slot.rain_mm if slot else None
        raining = weather or (rain is not None and rain >= 5) or (live_rain is not None and live_rain >= LIVE_RAIN_MM_H)
        parts = (["konteks cuaca aktif"] if weather else []) + \
            ([f"Open-Meteo saat ini {live_rain:g} mm/jam"] if live_rain is not None else []) + \
            ([f"prakiraan BMKG slot berjalan {rain:g} mm/3 jam"] if rain is not None else [])
        add("hujan", "ok" if raining == said_up else "tidak",  # hujan mendukung laporan naik; kering mendukung normal
            ", ".join(parts) + ". Hanya pendukung: banjir kiriman dari hulu bisa terjadi tanpa hujan di lokasi")

    # 3. pelapor lain & tanda periksa
    unique = 1
    if report.incident_id:
        inc = db.get(Incident, report.incident_id)
        unique = inc.unique_reporters if inc else 1
    add("pelapor", "ok" if unique >= 2 else "kurang", f"{unique} pelapor unik pada kejadian ini")
    flags = report.flags or []
    add("tanda_periksa", "tidak" if flags else "ok", ", ".join(flags) if flags else "Tidak ada tanda periksa")
    if report.status == ReportStatus.DUPLIKAT:
        add("duplikat", "tidak", "Laporan duplikat dari pelapor yang sama")

    res = {c["pemeriksaan"]: c["hasil"] for c in checks}
    river, hujan = res.get("sungai"), res.get("hujan")
    if river == "ok":  # angka pos sejalan dengan laporan; hujan tidak wajib
        verdict = "sesuai"
    elif river == "tidak":
        verdict = "sebagian" if hujan == "ok" else "tidak_sesuai"
    else:
        verdict = "sebagian" if hujan == "ok" else "data_kurang"
    return {"report_id": report.id, "hasil": verdict, "banjir": raised, "pemeriksaan": checks,
            "catatan": "Pencocokan hanya alat bantu; keputusan verifikasi tetap di pos pantau. Laporan tidak dihapus "
                       "walaupun hasilnya tidak sesuai."}
