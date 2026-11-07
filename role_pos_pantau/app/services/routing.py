"""Rute jalan kaki ke shelter via OSRM + pengecekan bahaya di sepanjang rute.

Rute OSRM = jalan terpendek dari data peta umum, TIDAK otomatis aman (PRD §14.2). Label "aman" hanya
untuk rute evakuasi resmi berstatus terverifikasi.
"""
import logging
from math import cos, radians

import httpx

from app.config import settings
from app.services.geo import haversine_m

log = logging.getLogger("riksa.routing")
WALK_MPS = 1.2  # ~4,3 km/jam untuk estimasi garis lurus
HAZARD_NEAR_M = 60
INCIDENT_NEAR_M = {"banjir": 250}
_cache: dict[tuple, list[dict] | None] = {}  # shortcut: cache per proses tanpa kedaluwarsa; cukup untuk demo

MODIFIER = {"left": "kiri", "right": "kanan", "slight left": "agak ke kiri", "slight right": "agak ke kanan",
            "sharp left": "tajam ke kiri", "sharp right": "tajam ke kanan", "straight": "lurus", "uturn": "putar balik"}


def _instruction(step: dict) -> str:
    m = step.get("maneuver", {})
    kind, mod = m.get("type", ""), MODIFIER.get(m.get("modifier", ""), "")
    road = step.get("name") or "jalan tanpa nama"
    dist = f" ({step.get('distance', 0):.0f} m)"
    if kind == "depart":
        return f"Mulai dari {road}{dist}"
    if kind == "arrive":
        return "Tiba di shelter"
    if kind in ("roundabout", "rotary"):
        return f"Masuk bundaran, keluar ke {road}{dist}"
    if kind == "end of road":
        return f"Di ujung jalan belok {mod} ke {road}{dist}"
    if kind == "fork":
        return f"Ambil cabang {mod} ke {road}{dist}"
    if kind in ("continue", "new name"):
        return f"Lanjut {mod or 'lurus'} di {road}{dist}"
    return f"Belok {mod} ke {road}{dist}" if mod else f"Lanjut ke {road}{dist}"


def osrm_routes(lat1: float, lng1: float, lat2: float, lng2: float) -> list[dict] | None:
    if not settings.routing_url:
        return None
    key = (round(lat1, 5), round(lng1, 5), round(lat2, 5), round(lng2, 5))
    if key in _cache:
        return _cache[key]
    try:
        r = httpx.get(f"{settings.routing_url}/{lng1},{lat1};{lng2},{lat2}",
                      params={"overview": "full", "geometries": "geojson", "alternatives": "true", "steps": "true"},
                      headers={"User-Agent": "RiksaWarga/1.0 (hackathon)"}, timeout=8)
        data = r.json()
    except (httpx.HTTPError, ValueError) as e:
        log.warning("OSRM gagal: %s", type(e).__name__)
        return None  # tidak di-cache: coba lagi lain kali
    if data.get("code") != "Ok":
        return None
    routes = [{
        "distance_m": round(rt["distance"]), "duration_s": round(rt["duration"]),
        "points": [[lat, lng] for lng, lat in rt["geometry"]["coordinates"]],
        "steps": [_instruction(s) for leg in rt.get("legs", []) for s in leg.get("steps", [])],
    } for rt in data.get("routes", [])]
    _cache[key] = routes
    return routes


def straight_line(lat1: float, lng1: float, lat2: float, lng2: float) -> dict:
    d = haversine_m(lat1, lng1, lat2, lng2)
    return {"distance_m": round(d), "duration_s": round(d / WALK_MPS), "points": [[lat1, lng1], [lat2, lng2]],
            "steps": ["Data jalan tidak tersedia: ikuti arah ke shelter, utamakan rute resmi dan arahan petugas."]}


def _point_segment_m(p: list[float], a: list[float], b: list[float]) -> float:
    # proyeksi equirectangular lokal: cukup akurat untuk jarak < beberapa km
    k = cos(radians(p[0]))
    ax, ay, bx, by, px, py = a[1] * k, a[0], b[1] * k, b[0], p[1] * k, p[0]
    dx, dy = bx - ax, by - ay
    t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return haversine_m(p[0], p[1], ay + t * dy, (ax + t * dx) / k)


def distance_to_line(p: list[float], points: list[list[float]]) -> float:
    if len(points) == 1:
        return haversine_m(p[0], p[1], points[0][0], points[0][1])
    return min(_point_segment_m(p, points[i], points[i + 1]) for i in range(len(points) - 1))


def hazards_near(points: list[list[float]], hazards: list[dict]) -> list[dict]:
    """hazards: {kind, label, lat, lng, radius_m}. Kembalikan yang dilewati rute."""
    out = []
    for h in hazards:
        d = distance_to_line([h["lat"], h["lng"]], points)
        if d <= h["radius_m"]:
            out.append({**h, "distance_m": round(d)})
    return out
