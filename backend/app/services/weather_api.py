"""Integrasi Live Weather API (Open-Meteo) untuk wilayah Kota Bandung.

Menyediakan data curah hujan dinamis, temperatur, kelembapan, kecepatan angin,
dan status kondisi cuaca secara realtime dengan sistem caching.
"""
import logging
import time
from datetime import datetime

import httpx

from app.db import utcnow

log = logging.getLogger("riksa.weather")

_CACHE: dict = {}
_CACHE_TIME: float = 0.0
CACHE_TTL_SECONDS = 60.0  # cache 1 menit untuk efisiensi


def _wmo_to_condition(code: int, rain: float) -> str:
    """Konversi WMO Weather Code ke deskripsi bahasa Indonesia."""
    if code == 0:
        return "Cerah"
    if code in (1, 2):
        return "Cerah Berawan"
    if code == 3:
        return "Berawan Tebal"
    if code in (45, 48):
        return "Berkabut"
    if code in (51, 53, 55):
        return "Gerimis / Hujan Ringan"
    if code in (61, 63):
        return "Hujan Sedang"
    if code == 65:
        return "Hujan Lebat (Potensi Genangan)"
    if code in (80, 81):
        return "Hujan Deras Lokal"
    if code == 82:
        return "Hujan Sangat Deras (Risiko Luapan)"
    if code in (95, 96, 99):
        return "Badai Petir & Hujan Deras"
    if rain > 15.0:
        return "Hujan Lebat (Potensi Luapan)"
    if rain > 5.0:
        return "Hujan Sedang"
    if rain > 0.0:
        return "Hujan Ringan"
    return "Berawan"


async def get_bandung_live_weather(lat: float = -6.9175, lng: float = 107.6191) -> dict:
    """Ambil data cuaca Bandung terkini dari Open-Meteo API."""
    global _CACHE, _CACHE_TIME
    now_ts = time.time()
    if _CACHE and (now_ts - _CACHE_TIME < CACHE_TTL_SECONDS):
        return _CACHE

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lng,
        "current": "temperature_2m,relative_humidity_2m,precipitation,rain,weather_code,wind_speed_10m",
        "timezone": "Asia/Jakarta",
    }
    try:
        async with httpx.AsyncClient(timeout=3.5) as client:
            resp = await client.get(url, params=params)
            if resp.status_code == 200:
                data = resp.json().get("current", {})
                code = int(data.get("weather_code", 0))
                rain = float(data.get("rain", 0.0))
                precip = float(data.get("precipitation", rain))
                condition_desc = _wmo_to_condition(code, rain)

                result = {
                    "location": "Kota Bandung (DAS Cikapundung)",
                    "latitude": lat,
                    "longitude": lng,
                    "temperature_c": float(data.get("temperature_2m", 24.0)),
                    "humidity_pct": int(data.get("relative_humidity_2m", 80)),
                    "precipitation_mm": precip,
                    "rain_mm": rain,
                    "wind_speed_kmh": float(data.get("wind_speed_10m", 10.0)),
                    "condition": condition_desc,
                    "weather_code": code,
                    "source": "Open-Meteo Live API (Kota Bandung)",
                    "updated_at": utcnow().isoformat(),
                    "is_live_api": True,
                    "stale": False,
                    "available": True,
                }
                _CACHE = result
                _CACHE_TIME = now_ts
                return result
    except Exception as e:
        log.warning("Gagal fetch data cuaca Open-Meteo (%s)", type(e).__name__)

    # Sumber gagal (PRD FR-013/014): jangan menampilkan angka karangan. Pakai data terakhir yang BENAR-BENAR
    # pernah diambil dan tandai kedaluwarsa; bila belum pernah ada, nyatakan tidak tersedia.
    if _CACHE:
        return {**_CACHE, "is_live_api": False, "stale": True, "available": True,
                "source": f"{_CACHE.get('source', 'Open-Meteo')} — DATA LAMA (sumber gagal diakses)"}
    return {
        "location": "Kota Bandung (DAS Cikapundung)", "latitude": lat, "longitude": lng,
        "temperature_c": None, "humidity_pct": None, "precipitation_mm": None, "rain_mm": None,
        "wind_speed_kmh": None, "condition": "Data cuaca tidak tersedia", "weather_code": None,
        "source": "Open-Meteo — gagal diakses", "updated_at": None, "is_live_api": False,
        "stale": True, "available": False,
    }

