"""Kondisi alam dinamis + prediksi risiko banjir (PRD v2 §7.1).

PREDIKSI = PERKIRAAN BANTU berbasis aturan transparan, bukan deteksi dan bukan kepastian. Ambang di bawah adalah
asumsi awal untuk diuji dan dikalibrasi dengan data historis/BPBD (PRD D-05), bukan nilai ilmiah.
Data kedaluwarsa tidak dipakai sebagai kondisi sekarang."""
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import area_scope_ids
from app.models import Alert, ForecastSlot, Observation, Region, RegionLevel, RiskState, RiverLevel, Station
from app.services import announce, weather_live
from app.services.disaster import latest_condition
from app.services.monitoring import is_stale, latest_observation, level_status, trend_direction

RAIN_6H_MED, RAIN_6H_HIGH, RAIN_24H_HIGH = 10.0, 30.0, 60.0  # mm (asumsi uji)
ETA_NEAR_H, ETA_FAR_H = 3.0, 6.0  # jam menuju ambang waspada
LEVEL_RANK = {"rendah": 0, "sedang": 1, "tinggi": 2}
RISK_NOTE = ("Prediksi adalah PERKIRAAN berdasarkan prakiraan hujan BMKG dan kondisi sungai, bukan kepastian. "
             "Ikuti pengumuman pos pantau dan instruksi resmi BPBD.")


def rate_cm_per_hour(db: Session, station: Station, now: datetime) -> float | None:
    """Laju perubahan dari pembacaan 3 jam terakhir (nilai pertama vs terakhir)."""
    rows = db.scalars(select(Observation).where(
        Observation.station_id == station.id, Observation.observed_at >= now - timedelta(hours=3))
        .order_by(Observation.observed_at, Observation.id)).all()
    if len(rows) < 2:
        return None
    hours = (rows[-1].observed_at - rows[0].observed_at).total_seconds() / 3600
    return None if hours <= 0 else (rows[-1].level_cm - rows[0].level_cm) / hours


def station_nature(db: Session, station: Station, now: datetime) -> dict:
    obs = latest_observation(db, station.id)
    stale = is_stale(obs, now)
    readings = db.scalars(select(Observation).where(
        Observation.station_id == station.id, Observation.observed_at >= now - timedelta(hours=6))
        .order_by(Observation.observed_at, Observation.id)).all()
    rate = rate_cm_per_hour(db, station, now)
    eta = None
    if obs and not stale and rate and rate > 0 and obs.level_cm < station.warning_cm:
        eta = round((station.warning_cm - obs.level_cm) / rate, 1)
    cond = latest_condition(db, station.id, now)
    return {
        "id": station.id, "name": station.name, "region_id": station.region_id, "lat": station.lat, "lng": station.lng,
        "is_upstream": station.is_upstream, "river_name": station.river_name,
        "warning_cm": station.warning_cm, "danger_cm": station.danger_cm,
        "level_cm": None if obs is None or stale else obs.level_cm, "level_at": obs.observed_at if obs else None,
        "level_mode": obs.source_mode.value if obs else None, "level_status": level_status(station, obs, now),
        "trend": trend_direction(list(readings)), "rate_cm_per_hour": None if rate is None else round(rate, 1),
        "eta_to_warning_hours": eta,
        "condition": None if cond is None else {**cond, "status": cond["status"].value,
                                                 "source_mode": cond["source_mode"].value},
        "readings": [{"t": o.observed_at, "cm": o.level_cm} for o in readings][-24:],
    }


def forecast_for(db: Session, region_id: int, now: datetime, hours: int = 24) -> list[dict]:
    """Slot prakiraan yang masih relevan (slot berjalan + sampai `hours` jam ke depan)."""
    area = area_scope_ids(db, region_id)
    rows = db.scalars(select(ForecastSlot).where(
        ForecastSlot.region_id.in_(area | {region_id}), ForecastSlot.slot_start > now - timedelta(hours=3),
        ForecastSlot.slot_start <= now + timedelta(hours=hours)).order_by(ForecastSlot.slot_start)).all()
    return [{"slot_start": r.slot_start, "rain_mm": r.rain_mm, "description": r.description, "source": r.source,
             "label": "prakiraan"} for r in rows]


def predict(db: Session, region: Region, now: datetime) -> dict:
    """Risiko banjir satu kelurahan: rendah | sedang | tinggi + alasan, jendela waktu, dan tingkat keyakinan."""
    score, reasons, inputs = 0, [], set()
    slots = forecast_for(db, region.id, now, 24)
    if slots:
        inputs.add("hujan")
        rain6 = sum(s["rain_mm"] for s in slots if s["slot_start"] < now + timedelta(hours=6))
        rain24 = sum(s["rain_mm"] for s in slots)
        if rain6 >= RAIN_6H_HIGH:
            score += 3
            reasons.append(f"Prakiraan hujan {rain6:g} mm dalam 6 jam ke depan (lebat)")
        elif rain6 >= RAIN_6H_MED:
            score += 2
            reasons.append(f"Prakiraan hujan {rain6:g} mm dalam 6 jam ke depan")
        if rain24 >= RAIN_24H_HIGH:
            score += 1
            reasons.append(f"Total prakiraan hujan {rain24:g} mm dalam 24 jam")
    live = weather_live.cached()  # Open-Meteo: hujan saat ini (tanpa jaringan di sini; hanya cache segar)
    if live and live.get("rain_mm_per_hour") is not None:
        inputs.add("hujan")
        rain_now = live["rain_mm_per_hour"]
        if rain_now >= 5:
            score += 2
            reasons.append(f"Hujan saat ini {rain_now:g} mm/jam (Open-Meteo)")
        elif rain_now >= 1:
            score += 1
            reasons.append(f"Hujan saat ini {rain_now:g} mm/jam (Open-Meteo)")
    simulated = False
    stations = list(db.scalars(select(Station).where(Station.region_id.in_(area_scope_ids(db, region.id)))))
    for st in stations:
        n = station_nature(db, st, now)
        cond = n["condition"]
        if cond and not cond["stale"]:
            inputs.add("kondisi_sungai")
            simulated = simulated or cond["source_mode"] == "simulation"
            if cond["status"] == RiverLevel.MELUAP.value:
                score += 4
                reasons.append(f"{st.name}: kondisi sungai MELUAP")
            elif cond["status"] == RiverLevel.WASPADA.value:
                score += 2
                reasons.append(f"{st.name}: kondisi sungai WASPADA")
        if n["level_cm"] is not None:
            inputs.add("tinggi_air")
            simulated = simulated or n["level_mode"] == "simulation"
            if n["level_cm"] >= st.danger_cm:
                score += 4
                reasons.append(f"{st.name}: tinggi air {n['level_cm']:g} cm melewati ambang bahaya")
            elif n["level_cm"] >= st.warning_cm:
                score += 2
                reasons.append(f"{st.name}: tinggi air {n['level_cm']:g} cm melewati ambang waspada")
            if n["trend"] == "naik":
                score += 1
                reasons.append(f"{st.name}: tinggi air naik ({n['rate_cm_per_hour']} cm/jam)")
        eta = n["eta_to_warning_hours"]
        if eta is not None and eta <= ETA_NEAR_H:
            score += 2
            reasons.append(f"{st.name}: diperkirakan mencapai ambang waspada ~{eta:g} jam lagi")
        elif eta is not None and eta <= ETA_FAR_H:
            score += 1
            reasons.append(f"{st.name}: diperkirakan mencapai ambang waspada ~{eta:g} jam lagi")
    level = "tinggi" if score >= 6 else "sedang" if score >= 3 else "rendah"
    confidence = "tinggi" if {"hujan", "kondisi_sungai"} <= inputs or {"hujan", "tinggi_air"} <= inputs \
        else "sedang" if inputs else "rendah"
    if not reasons:
        reasons = ["Tidak ada indikator risiko dari data yang tersedia"
                   if inputs else "Data belum cukup (tidak ada prakiraan atau pengamatan terbaru)"]
    return {"region_id": region.id, "area": region.name, "level": level, "score": score, "window_hours": 24,
            "reasons": reasons, "confidence": confidence, "inputs": sorted(inputs), "simulation": simulated,
            "computed_at": now, "note": RISK_NOTE}


def overview(db: Session, now: datetime) -> dict:
    """Kondisi alam seluruh kota (semua role non-admin): sungai, hujan, prediksi."""
    stations = [station_nature(db, s, now) for s in db.scalars(select(Station).order_by(Station.id))]
    areas = []
    for region in db.scalars(select(Region).where(Region.level == RegionLevel.KELURAHAN).order_by(Region.id)):
        areas.append({**predict(db, region, now), "forecast": forecast_for(db, region.id, now, 24)})
    return {"generated_at": now, "stations": stations, "areas": areas, "note": RISK_NOTE}


def prediction_tick(db: Session, now: datetime) -> list[Alert]:
    """Hitung ulang risiko per kelurahan; buat notifikasi bila risiko NAIK ke sedang/tinggi (deduplikasi)."""
    fired: list[Alert] = []
    for region in db.scalars(select(Region).where(Region.level == RegionLevel.KELURAHAN)):
        p = predict(db, region, now)
        state = db.get(RiskState, region.id)
        old = LEVEL_RANK[state.level] if state else 0
        if LEVEL_RANK[p["level"]] > old and p["level"] != "rendah":
            fired.append(announce.prediction_alert(db, region.id, region.name, p["level"], p["reasons"], now))
        if state is None:
            db.add(RiskState(region_id=region.id, level=p["level"], score=p["score"], reasons=p["reasons"],
                             computed_at=now))
        else:
            state.level, state.score, state.reasons, state.computed_at = p["level"], p["score"], p["reasons"], now
    return fired


# ---------- Live Monitoring (semua role non-admin) ----------
STATUS_SHOW = {"bahaya": "meluap"}  # tampilan: Normal / Waspada / Meluap


def station_live(db: Session, station: Station, now: datetime) -> dict:
    obs = latest_observation(db, station.id)
    status = level_status(station, obs, now)
    recent = db.scalars(select(Observation).where(
        Observation.station_id == station.id, Observation.observed_at >= now - timedelta(minutes=30))
        .order_by(Observation.observed_at.desc(), Observation.id.desc()).limit(3)).all()
    cond = latest_condition(db, station.id, now)
    return {
        "id": station.id, "name": station.name, "region_id": station.region_id, "lat": station.lat, "lng": station.lng,
        "is_upstream": station.is_upstream, "river_name": station.river_name,
        "warning_cm": station.warning_cm, "danger_cm": station.danger_cm,
        "level_cm": None if obs is None or is_stale(obs, now) else obs.level_cm,
        "level_at": obs.observed_at if obs else None, "level_mode": obs.source_mode.value if obs else None,
        "status": STATUS_SHOW.get(status, status), "trend": trend_direction(list(reversed(recent))),
        "note": obs.note if obs else None,
        "condition": None if cond is None else {**cond, "status": cond["status"].value,
                                                 "source_mode": cond["source_mode"].value},
    }


def station_detail(db: Session, station: Station, now: datetime, max_points: int = 144) -> dict:
    """Detail + grafik 12 jam terakhir (dicuplik maks. `max_points` titik agar ringan)."""
    rows = db.scalars(select(Observation).where(
        Observation.station_id == station.id, Observation.observed_at >= now - timedelta(hours=12))
        .order_by(Observation.observed_at, Observation.id)).all()
    step = max(1, -(-len(rows) // max_points))
    sample = rows[::step]
    if rows and sample[-1] is not rows[-1]:
        sample.append(rows[-1])  # titik terakhir selalu tampil
    return {**station_live(db, station, now),
            "readings": [{"observed_at": o.observed_at, "level_cm": o.level_cm, "source_mode": o.source_mode.value}
                         for o in sample]}


def live(db: Session, now: datetime) -> dict:
    return {"generated_at": now, "weather": weather_live.current(),
            "stations": [station_live(db, s, now) for s in db.scalars(select(Station).order_by(Station.id))],
            "note": "Tinggi muka air (TMA) berasal dari simulator langsung karena sensor belum terpasang (berlabel "
                    "SIMULASI); cuaca dari Open-Meteo."}
