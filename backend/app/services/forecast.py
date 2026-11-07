"""Prakiraan hujan (Open-Meteo) dan prediksi Potensi Banjir berbasis aturan (PRD §7.1, FR-017–019).

PERKIRAAN BANTU, BUKAN DETEKSI. Ambang dan bobot di bawah adalah asumsi uji (D-05) yang harus dikalibrasi
dengan data historis dan masukan BPBD. Tidak ada data yang dikarang: bila prakiraan hujan gagal diambil,
hasilnya ditandai "tidak tersedia" dan tingkat keyakinan turun.
"""
import logging
import time
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import ancestor_at_level
from app.config import settings
from app.db import utcnow
from app.models import AlertKind, AlertLevel, Observation, RegionLevel, Station, Verification
from app.services.alerting import emit

log = logging.getLogger("riksa.forecast")
BANDUNG = (-6.9175, 107.6191)
WIB = timezone(timedelta(hours=7))
CACHE_TTL = 600.0  # 10 menit
LABEL = "Perkiraan bantu, bukan deteksi banjir. Ambang dan bobot adalah asumsi uji dan belum dikalibrasi."

# asumsi uji: curah hujan (mm) pada jendela waktu
RAIN_3H_HIGH, RAIN_6H_HIGH, RAIN_6H_MID, RAIN_6H_LOW, PEAK_HOURLY_HIGH = 20.0, 30.0, 15.0, 5.0, 20.0

_cache: dict = {"at": 0.0, "data": None, "error": None}


def fetch_hourly(now_ts: float | None = None) -> dict | None:
    """Prakiraan hujan per jam, 3 jam terakhir + 24 jam ke depan. None bila belum pernah berhasil."""
    t = now_ts or time.time()
    if _cache["data"] and t - _cache["at"] < CACHE_TTL:
        return _cache["data"]
    params = {"latitude": BANDUNG[0], "longitude": BANDUNG[1], "timezone": "Asia/Jakarta",
              "hourly": "precipitation,precipitation_probability", "past_hours": 3, "forecast_hours": 24}
    try:
        r = httpx.get(settings.forecast_url, params=params, timeout=6)
        r.raise_for_status()
        h = r.json()["hourly"]
        hours = []
        for i, ts in enumerate(h["time"]):
            when = datetime.fromisoformat(ts).replace(tzinfo=WIB).astimezone(timezone.utc).replace(tzinfo=None)
            prob = (h.get("precipitation_probability") or [None] * len(h["time"]))[i]
            hours.append({"at": when.isoformat(), "mm": float(h["precipitation"][i] or 0.0), "prob": prob})
        data = {"hours": hours, "fetched_at": utcnow().isoformat(), "source": "Open-Meteo (prakiraan model)"}
        _cache.update(at=t, data=data, error=None)
        return data
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as e:
        log.warning("Prakiraan hujan gagal diambil: %s", type(e).__name__)
        _cache["error"] = type(e).__name__
        return _cache["data"]  # data lama (ditandai stale oleh pemanggil) atau None


def rain_summary(now: datetime) -> dict:
    data = fetch_hourly()
    if not data:
        return {"available": False, "stale": True, "source": "Open-Meteo", "error": _cache["error"], "hours": []}
    fetched = datetime.fromisoformat(data["fetched_at"])
    stale = now - fetched > timedelta(minutes=45)
    future = [h for h in data["hours"] if datetime.fromisoformat(h["at"]) >= now.replace(minute=0, second=0, microsecond=0)]
    nxt = lambda n: round(sum(h["mm"] for h in future[:n]), 1)  # noqa: E731
    peak = max(future, key=lambda h: h["mm"], default=None)
    hours_to_peak = None
    if peak is not None:
        hours_to_peak = max(0, round((datetime.fromisoformat(peak["at"]) - now).total_seconds() / 3600))
    return {"available": True, "stale": stale, "source": data["source"], "fetched_at": data["fetched_at"],
            "next3_mm": nxt(3), "next6_mm": nxt(6), "next24_mm": nxt(24),
            "peak_mm_per_h": peak["mm"] if peak else 0.0, "peak_at": peak["at"] if peak else None,
            "hours_to_peak": hours_to_peak, "hours": future[:24]}


def rain_recent_mm(now: datetime) -> float | None:
    """Curah hujan (mm) dari 3 jam lalu sampai 1 jam ke depan menurut model; None bila data tidak ada."""
    data = fetch_hourly()
    if not data:
        return None
    lo, hi = now - timedelta(hours=3), now + timedelta(hours=1)
    return round(sum(h["mm"] for h in data["hours"] if lo < datetime.fromisoformat(h["at"]) <= hi), 1)


def _rain_points(rain: dict) -> tuple[int, list[str]]:
    if not rain["available"]:
        return 0, ["Prakiraan hujan tidak tersedia"]
    pts, why = 0, []
    if rain["next6_mm"] >= RAIN_6H_HIGH or rain["next3_mm"] >= RAIN_3H_HIGH:
        pts, why = 3, [f"Hujan lebat diprakirakan: {rain['next6_mm']} mm dalam 6 jam ke depan"]
    elif rain["next6_mm"] >= RAIN_6H_MID or rain["peak_mm_per_h"] >= PEAK_HOURLY_HIGH:
        pts, why = 2, [f"Hujan cukup deras diprakirakan: {rain['next6_mm']} mm dalam 6 jam (puncak {rain['peak_mm_per_h']} mm/jam)"]
    elif rain["next6_mm"] >= RAIN_6H_LOW:
        pts, why = 1, [f"Hujan ringan-sedang diprakirakan: {rain['next6_mm']} mm dalam 6 jam"]
    else:
        why = [f"Hujan 6 jam ke depan rendah ({rain['next6_mm']} mm)"]
    if rain["stale"]:
        why.append("Prakiraan hujan sudah lama (kedaluwarsa)")
    return pts, why


def _trend(db: Session, station: Station, now: datetime) -> tuple[str, float | None, bool, float | None]:
    """(arah, laju cm/menit, ada_data_segar, level_terakhir) dari pengamatan 60 menit terakhir."""
    rows = db.scalars(select(Observation).where(
        Observation.station_id == station.id, Observation.observed_at >= now - timedelta(minutes=60))
        .order_by(Observation.observed_at, Observation.id)).all()
    if len(rows) < 3:
        return "belum_cukup_data", None, bool(rows), rows[-1].level_cm if rows else None
    # rata-rata awal vs akhir meredam jitter pengukuran
    k = max(1, len(rows) // 3)
    first = sum(r.level_cm for r in rows[:k]) / k
    last = sum(r.level_cm for r in rows[-k:]) / k
    minutes = max(1.0, (rows[-1].observed_at - rows[0].observed_at).total_seconds() / 60)
    slope = (last - first) / minutes
    direction = "naik" if last - first > 5 else "turun" if first - last > 5 else "stabil"
    return direction, slope, True, rows[-1].level_cm


def predict_station(db: Session, station: Station, rain: dict, now: datetime, upstream_alarm: bool) -> dict:
    reasons: list[str] = []
    rain_pts, rain_why = _rain_points(rain)
    reasons += rain_why
    cond = station.condition or "normal"
    river_pts = {"normal": 0, "waspada": 2, "meluap": 4}.get(cond, 0)
    reasons.append(f"Kondisi sungai saat ini (pos pantau): {cond.upper()}")
    direction, slope, has_obs, level = _trend(db, station, now)
    if direction == "naik":
        river_pts += 1
        reasons.append("Tinggi air cenderung naik dalam 1 jam terakhir")
    if level is not None and level >= station.warning_cm and cond == "normal":
        river_pts += 1
        reasons.append(f"Tinggi air {level:.0f} cm sudah melewati ambang waspada {station.warning_cm:.0f} cm")
    if not station.is_upstream and upstream_alarm:
        river_pts += 1
        reasons.append("Sungai di hulu berstatus Waspada/Meluap")

    score = rain_pts + river_pts
    risk = "tinggi" if cond == "meluap" or score >= 5 else "sedang" if score >= 3 else "rendah"
    window = 24
    if rain["available"] and rain.get("hours_to_peak") is not None:
        window = next((w for w in (3, 6, 12, 24) if rain["hours_to_peak"] <= w), 24)
    if cond == "meluap":
        window = 3

    cond_fresh = bool(station.condition_at and now - station.condition_at < timedelta(hours=settings.condition_stale_hours))
    fresh_inputs = (1 if rain["available"] and not rain["stale"] else 0) + (1 if cond_fresh or has_obs else 0)
    confidence = ("tinggi", "sedang", "rendah")[2 - fresh_inputs] if fresh_inputs <= 2 else "rendah"
    if not cond_fresh and station.condition_at is not None:
        reasons.append("Kondisi sungai belum diperbarui pos pantau dalam beberapa jam")

    eta = None
    if slope and slope > 0.1 and level is not None and level < station.warning_cm and cond == "normal":
        mins = (station.warning_cm - level) / slope  # FR-018: estimasi dengan rentang
        eta = {"to": "waspada", "minutes_low": max(1, round(mins * 0.5)), "minutes_high": round(mins * 1.5)}
    return {"station_id": station.id, "name": station.name, "river": station.river_name, "region_id": station.region_id,
            "lat": station.lat, "lng": station.lng, "risk": risk, "score": score, "window_hours": window,
            "confidence": confidence, "reasons": reasons, "condition": cond, "trend": direction, "eta_to_threshold": eta}


def predict(db: Session, now: datetime | None = None) -> dict:
    now = now or utcnow()
    rain = rain_summary(now)
    stations = list(db.scalars(select(Station).order_by(Station.id)))
    upstream_alarm = any(s.is_upstream and (s.condition or "normal") != "normal" for s in stations)
    items = [predict_station(db, s, rain, now, upstream_alarm) for s in stations]
    order = {"rendah": 0, "sedang": 1, "tinggi": 2}
    top = max(items, key=lambda i: order[i["risk"]], default=None)
    city = {"risk": top["risk"] if top else "rendah", "window_hours": top["window_hours"] if top else 24,
            "confidence": top["confidence"] if top else "rendah",
            "reasons": top["reasons"] if top else ["Belum ada pos pantau"],
            "station": top["name"] if top else None}
    return {"generated_at": now.isoformat(), "label": LABEL, "rain": rain, "city": city, "stations": items}


def notify_predictions(db: Session, now: datetime | None = None) -> list:
    """Notifikasi saat risiko Sedang/Tinggi (FR-019). Dedupe per pos+tingkat selama 3 jam; SMS hanya untuk Tinggi."""
    now = now or utcnow()
    alerts = []
    for item in predict(db, now)["stations"]:
        if item["risk"] == "rendah":
            continue
        station = db.get(Station, item["station_id"])
        audience = ancestor_at_level(db, station.region_id, RegionLevel.KELURAHAN) or station.region_id
        high = item["risk"] == "tinggi"
        why = "\n".join(f"- {r}" for r in item["reasons"][:4])
        msg = (f"[RIKSA WARGA — PREDIKSI POTENSI BANJIR {item['risk'].upper()}]\n"
               f"Pos: {station.name} ({station.river_name or 'sungai'})\n"
               f"Status: PERKIRAAN untuk ±{item['window_hours']} jam ke depan — keyakinan {item['confidence']}\n"
               f"Alasan:\n{why}\n"
               "Tindakan: pantau informasi, siapkan dokumen penting dan tas siaga, kenali shelter terdekat. "
               "Ini perkiraan, bukan kepastian. Utamakan arahan BPBD/petugas.")
        a = emit(db, kind=AlertKind.PREDIKSI, level=AlertLevel.SIAGA if high else AlertLevel.WASPADA,
                 verification=Verification.BELUM, audience_region_id=audience, station_id=station.id, message=msg,
                 sms=high, dedupe_key=f"pred:{station.id}:{item['risk']}", dedupe_minutes=180, now=now)
        if a is not None:
            alerts.append(a)
    return alerts
