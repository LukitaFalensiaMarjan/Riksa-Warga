"""Live Monitoring: simulator TMA tiap tick untuk semua pos, tombol kondisi pos pantau, cuaca Open-Meteo, detail pos."""
import random
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.config import settings
from app.db import utcnow
from app.models import Alert, AlertKind, Observation, SourceMode, Station
from app.services import live_sim, nature, weather_live

STATIONS = 7


def _station(db, name="Pos Pantau Hulu"):
    return db.scalar(select(Station).where(Station.name == name))


def _levels(db, station_id):
    db.expire_all()
    return [o.level_cm for o in db.scalars(select(Observation).where(Observation.station_id == station_id)
                                           .order_by(Observation.observed_at, Observation.id))]


# ---------- simulator ----------
def test_bands_follow_thresholds(db):
    st = _station(db)  # waspada 150, bahaya 250
    assert live_sim.band(st, "normal") == (60.0, 93.0)
    assert live_sim.band(st, "waspada") == (150, 230.0)
    lo, hi = live_sim.band(st, "meluap")
    assert lo == 250 and hi > 250
    assert [live_sim.level_label(st, v) for v in (100, 150, 249.9, 250)] == ["normal", "waspada", "waspada", "meluap"]


def test_next_level_moves_toward_band_and_stays_inside():
    rng = random.Random(1)
    assert live_sim.next_level(None, 60, 90) == 75.0
    v = 20.0
    for _ in range(40):
        v = live_sim.next_level(v, 150, 230, rng)
    assert 150 <= v <= 230  # naik bertahap sampai masuk pita
    for _ in range(200):
        v = live_sim.next_level(v, 150, 230, rng)
        assert 150 <= v <= 230


def test_tick_adds_one_simulated_reading_per_station_every_time(db):
    rng = random.Random(2)
    now = utcnow()
    for i in range(3):
        live_sim.tick(db, now + timedelta(seconds=3 * i), rng)
    db.commit()
    rows = db.scalars(select(Observation)).all()
    assert len(rows) == 3 * STATIONS
    assert {o.source_mode for o in rows} == {SourceMode.SIMULATION}
    hulu = _station(db)
    assert all(60 <= v <= 93 for v in _levels(db, hulu.id))  # kondisi default: normal
    assert {o.note for o in rows} == {live_sim.NOTES["normal"]}


def test_seed_history_fills_12_hours_once(db):
    now = utcnow()
    n = live_sim.seed_history(db, now, random.Random(3))
    db.commit()
    assert n == STATIONS * 144  # tiap 5 menit selama 12 jam
    assert live_sim.seed_history(db, now, random.Random(3)) == 0  # sudah ada data baru: tidak menggandakan
    first = db.scalar(select(Observation).order_by(Observation.observed_at))
    assert now - first.observed_at <= timedelta(hours=12)


def test_prune_keeps_only_recent_simulation(db):
    now = utcnow()
    live_sim.seed_history(db, now - timedelta(hours=10), random.Random(4))  # riwayat 22-10 jam lalu
    db.commit()
    removed = live_sim.prune(db, now)
    db.commit()
    assert removed > 0
    assert db.scalar(select(Observation).order_by(Observation.observed_at)).observed_at >= now - live_sim.KEEP


def test_condition_button_moves_data_and_status_for_every_role(client, login, ids, db, monkeypatch):
    monkeypatch.setattr(settings, "live_sim_seconds", 3)  # simulator aktif seperti di server
    sid = ids["Pos Pantau Hulu"]
    live_sim.tick(db, utcnow(), random.Random(5))
    db.commit()
    r = client.post(f"/stations/{sid}/condition", json={"status": "meluap", "note": "Uji tombol"}, headers=login("pospantau1"))
    assert r.status_code == 201
    assert _levels(db, sid)[-1] >= 250  # data langsung pindah ke pita Meluap
    for user in ("warga1", "koord_rw01", "pospantau2", "sar1"):
        d = client.get(f"/nature/stations/{sid}", headers=login(user)).json()
        assert d["status"] == "meluap" and d["condition"]["status"] == "meluap" and d["level_cm"] >= 250
    db.expire_all()
    kinds = {a.kind for a in db.scalars(select(Alert))}
    assert AlertKind.KONDISI in kinds and AlertKind.RISIKO in kinds  # notifikasi kondisi + risiko (lewat ambang)
    live_sim.tick(db, utcnow(), random.Random(6))  # tick berikutnya tetap di pita Meluap
    db.commit()
    assert _levels(db, sid)[-1] >= 250
    client.post(f"/stations/{sid}/condition", json={"status": "normal"}, headers=login("pospantau1"))
    assert _levels(db, sid)[-1] < 150


def test_condition_button_without_simulator_does_not_invent_data(client, login, ids, db):
    assert settings.live_sim_seconds == 0
    client.post(f"/stations/{ids['Pos Pantau Hulu']}/condition", json={"status": "meluap"}, headers=login("pospantau1"))
    assert _levels(db, ids["Pos Pantau Hulu"]) == []


# ---------- endpoint ----------
def test_live_endpoint_lists_all_stations_for_non_admin(client, login, db):
    live_sim.tick(db, utcnow(), random.Random(7))
    db.commit()
    for user in ("warga1", "koord_rw01", "pospantau1", "sar1"):
        r = client.get("/nature/live", headers=login(user))
        assert r.status_code == 200
        body = r.json()
        assert len(body["stations"]) == STATIONS and "SIMULASI" in body["note"]
        s = body["stations"][0]
        assert {"level_cm", "status", "trend", "warning_cm", "danger_cm", "lat", "lng", "note", "level_mode"} <= set(s)
        assert s["status"] == "normal" and s["level_mode"] == "simulation"
    assert client.get("/nature/live", headers=login("admin")).status_code == 403
    assert client.get("/nature/live").status_code == 401


def test_station_detail_has_12h_chart_downsampled(client, login, ids, db):
    live_sim.seed_history(db, utcnow(), random.Random(8))
    db.commit()
    d = client.get(f"/nature/stations/{ids['Pos Pantau Hilir']}", headers=login("warga1")).json()
    assert d["name"] == "Pos Pantau Hilir" and d["warning_cm"] == 120 and d["danger_cm"] == 200
    assert d["lat"] == -6.9 and d["region_id"] == ids["RT 01 / RW 02"]
    assert 100 <= len(d["readings"]) <= 145 and d["trend"] in ("naik", "turun", "stabil")
    assert d["note"] == live_sim.NOTES["normal"]
    assert client.get("/nature/stations/9999", headers=login("warga1")).status_code == 404
    assert client.get(f"/nature/stations/{ids['Pos Pantau Hilir']}", headers=login("admin")).status_code == 403


# ---------- cuaca Open-Meteo ----------
SAMPLE = {"current": {"time": "2026-11-07T14:15", "temperature_2m": 32.4, "relative_humidity_2m": 36,
                      "precipitation": 0.1, "rain": 0.1, "weather_code": 3, "wind_speed_10m": 1.7}}


def test_weather_is_parsed_and_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(weather_live, "http_get", lambda params: calls.append(params) or SAMPLE)
    w = weather_live.current()
    assert w["status"] == "ok" and w["temperature_c"] == 32.4 and w["humidity_pct"] == 36
    assert w["rain_mm_per_hour"] == 0.1 and w["wind_kmh"] == 1.7 and w["description"] == "Gerimis / Hujan Ringan"
    assert "Open-Meteo" in w["source"] and w["fetched_at"]
    weather_live.current()
    assert len(calls) == 1  # cache 60 detik
    assert calls[0]["latitude"] == weather_live.PLACE["lat"]


def test_weather_failure_keeps_system_running(client, login):
    w = client.get("/nature/live", headers=login("warga1")).json()["weather"]  # http_get gagal (fixture tes)
    assert w["status"] == "gagal" and w["stale"] is True and w["error"] == "OSError"


def test_live_rain_feeds_prediction(client, login, monkeypatch):
    heavy = {"current": {**SAMPLE["current"], "precipitation": 7.5, "rain": 7.5, "weather_code": 63}}
    monkeypatch.setattr(weather_live, "http_get", lambda params: heavy)
    weather_live.current(force=True)
    area = client.get("/nature", headers=login("warga1")).json()["areas"][0]
    assert any("Hujan saat ini 7.5 mm/jam (Open-Meteo)" in r for r in area["reasons"])
    assert area["level"] in ("rendah", "sedang") and "hujan" in area["inputs"]
