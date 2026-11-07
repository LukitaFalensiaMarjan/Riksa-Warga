"""Cuaca langsung Kota Bandung dari Open-Meteo (tanpa kunci API). Pengamatan model per 15 menit, bukan stasiun BMKG.

Disimpan di cache 60 detik agar banyak pengguna tidak membebani API; gagal -> data terakhir ditandai kedaluwarsa,
sistem tetap jalan."""
import threading
import time
from datetime import datetime

import httpx

URL = "https://api.open-meteo.com/v1/forecast"
PLACE = {"name": "Kota Bandung (DAS Cikapundung)", "lat": -6.9175, "lng": 107.6191}
CACHE_SECONDS = 60
STALE_SECONDS = 3600
SOURCE = "Open-Meteo Live API (Kota Bandung)"
WMO = {0: "Cerah", 1: "Cerah berawan", 2: "Berawan sebagian", 3: "Berawan", 45: "Berkabut", 48: "Berkabut",
       51: "Gerimis ringan", 53: "Gerimis", 55: "Gerimis lebat", 61: "Hujan ringan", 63: "Hujan sedang",
       65: "Hujan lebat", 80: "Hujan lokal ringan", 81: "Hujan lokal sedang", 82: "Hujan lokal lebat",
       95: "Badai petir", 96: "Badai petir + hujan es", 99: "Badai petir + hujan es"}

_lock = threading.Lock()
_cache: dict = {"data": None, "fetched": 0.0, "error": None, "wall": None}


def http_get(params: dict) -> dict:
    r = httpx.get(URL, params=params, timeout=10, headers={"User-Agent": "RiksaWarga/0.4"})
    r.raise_for_status()
    return r.json()


def describe(code: int | None, rain: float) -> str:
    text = WMO.get(code, "Kondisi tidak diketahui")
    if rain > 0 and "Hujan" not in text and "Gerimis" not in text:
        text = "Gerimis / Hujan Ringan"
    return text


def _parse(j: dict) -> dict:
    c = j["current"]
    rain = float(c.get("precipitation") or c.get("rain") or 0)
    return {"place": PLACE["name"], "time_local": c.get("time"), "temperature_c": c.get("temperature_2m"),
            "humidity_pct": c.get("relative_humidity_2m"), "rain_mm_per_hour": rain,
            "wind_kmh": c.get("wind_speed_10m"), "weather_code": c.get("weather_code"),
            "description": describe(c.get("weather_code"), rain), "source": SOURCE}


def current(force: bool = False) -> dict:
    """Cuaca terkini (cache 60 dtk). Tidak pernah melempar: gagal -> data lama + status gagal."""
    now = time.monotonic()
    with _lock:
        fresh = _cache["data"] is not None and now - _cache["fetched"] < CACHE_SECONDS
        if fresh and not force:
            return _view(now)
        try:
            data = _parse(http_get({"latitude": PLACE["lat"], "longitude": PLACE["lng"], "timezone": "Asia/Jakarta",
                                    "current": "temperature_2m,relative_humidity_2m,precipitation,rain,"
                                               "weather_code,wind_speed_10m"}))
            _cache.update(data=data, fetched=now, error=None, wall=datetime.utcnow())
        except Exception as e:  # sumber eksternal boleh gagal
            _cache["error"] = f"{type(e).__name__}"
        return _view(now)


def cached() -> dict | None:
    """Tanpa jaringan: dipakai mesin prediksi (hanya bila data masih segar)."""
    with _lock:
        if _cache["data"] is None or time.monotonic() - _cache["fetched"] > STALE_SECONDS:
            return None
        return dict(_cache["data"])


def _view(now: float) -> dict:
    d = _cache["data"]
    age = None if d is None else int(now - _cache["fetched"])
    return {"status": "ok" if _cache["error"] is None and d else "gagal", "error": _cache["error"],
            "stale": d is None or age > STALE_SECONDS, "age_seconds": age,
            "fetched_at": _cache["wall"].isoformat() + "Z" if d and _cache["wall"] else None,
            **(d or {"place": PLACE["name"], "source": SOURCE})}


def reset_cache() -> None:  # untuk tes
    with _lock:
        _cache.update(data=None, fetched=0.0, error=None, wall=None)
