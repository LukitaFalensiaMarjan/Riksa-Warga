"""Fitur Pos Pantau: tinggi air, tren, ambang, data kedaluwarsa, simulasi, indikasi sensor kebakaran."""
from datetime import timedelta

from app.db import utcnow
from conftest import aware


def _observe(client, login, station_id, level, user="pospantau1", expect=201, **extra):
    r = client.post(f"/stations/{station_id}/observations", json={"level_cm": level, **extra}, headers=login(user))
    assert r.status_code == expect, r.text
    return r.json()


# FR-023
def test_pos_pantau_records_water_level(client, login, ids):
    obs = _observe(client, login, ids["Pos Pantau Hulu"], 90, river_condition="naik", note="Air keruh")
    assert obs["unit"] == "cm"
    assert obs["level_cm"] == 90
    assert obs["river_condition"] == "naik"
    assert obs["source_mode"] == "real"
    assert obs["reported_by"] == ids["pospantau1"]


def test_warga_cannot_record_water_level(client, login, ids):
    _observe(client, login, ids["Pos Pantau Hulu"], 90, user="warga1", expect=403)


def test_pos_pantau_limited_to_assigned_station(client, login, ids):
    _observe(client, login, ids["Pos Pantau Hilir"], 90, user="pospantau1", expect=403)
    _observe(client, login, ids["Pos Pantau Hilir"], 90, user="pospantau2")


def test_observation_validation(client, login, ids):
    sid = ids["Pos Pantau Hulu"]
    _observe(client, login, sid, -5, expect=422)
    _observe(client, login, sid, 90, observed_at=aware(utcnow() + timedelta(hours=1)), expect=422)
    # tanpa zona waktu ditolak, agar jam lokal WIB tidak dibaca sebagai UTC
    _observe(client, login, sid, 90, observed_at=utcnow().isoformat(), expect=422)
    t = utcnow().replace(second=0, microsecond=0) - timedelta(minutes=1)
    wib = (t + timedelta(hours=7)).isoformat() + "+07:00"
    assert _observe(client, login, sid, 90, observed_at=wib)["observed_at"] == t.isoformat()  # disimpan sebagai UTC


# FR-015
def test_trend_direction_and_threshold_status(client, login, ids):
    sid = ids["Pos Pantau Hulu"]
    base = utcnow() - timedelta(minutes=20)
    for i, level in enumerate((100, 120, 140)):
        _observe(client, login, sid, level, observed_at=aware(base + timedelta(minutes=5 * i)))
    t = client.get(f"/stations/{sid}/trend", headers=login("pospantau1")).json()
    assert t["direction"] == "naik"
    assert t["status"] == "normal"
    assert [r["level_cm"] for r in t["readings"]] == [100, 120, 140]

    _observe(client, login, sid, 160)
    t = client.get(f"/stations/{sid}/trend", headers=login("koord_rw01")).json()
    assert t["status"] == "waspada"

    _observe(client, login, sid, 260)
    assert client.get(f"/stations/{sid}/trend", headers=login("warga1")).json()["status"] == "bahaya"


def test_stable_trend(client, login, ids):
    sid = ids["Pos Pantau Hulu"]
    base = utcnow() - timedelta(minutes=10)
    for i, level in enumerate((100, 102, 101)):
        _observe(client, login, sid, level, observed_at=aware(base + timedelta(minutes=3 * i)))
    assert client.get(f"/stations/{sid}/trend", headers=login("pospantau1")).json()["direction"] == "stabil"


# PRD §21.3: sensor/pos berhenti mengirim -> data kedaluwarsa, bukan nilai sekarang
def test_old_reading_marked_stale(client, login, ids):
    sid = ids["Pos Pantau Hulu"]
    _observe(client, login, sid, 200, observed_at=aware(utcnow() - timedelta(hours=2)))
    stations = {s["id"]: s for s in client.get("/stations", headers=login("koord_rw01")).json()}
    assert stations[sid]["stale"] is True
    assert stations[sid]["status"] == "data_kedaluwarsa"
    assert stations[sid]["latest"]["level_cm"] == 200  # nilai tetap terlihat beserta waktunya


def test_station_without_data(client, login, ids):
    stations = {s["id"]: s for s in client.get("/stations", headers=login("pospantau1")).json()}
    assert stations[ids["Pos Pantau Hulu"]]["status"] == "tidak_ada_data"


# FR-012: data simulasi berlabel
def test_simulation_label_kept(client, login, ids):
    sid = ids["Pos Pantau Hulu"]
    _observe(client, login, sid, 100, source_mode="simulation")
    stations = {s["id"]: s for s in client.get("/stations", headers=login("koord_rw01")).json()}
    assert stations[sid]["latest"]["source_mode"] == "simulation"


# PRD §9.1: lintas ambang = status risiko internal, bukan kejadian
def test_crossing_threshold_creates_internal_risk_notice(client, login, ids):
    sid = ids["Pos Pantau Hulu"]
    _observe(client, login, sid, 140)
    _observe(client, login, sid, 155)
    coord = client.get("/alerts", headers=login("koord_rw01")).json()
    risk = [a for a in coord if a["kind"] == "risiko"]
    assert len(risk) == 1
    assert risk[0]["internal"] is True and risk[0]["incident_id"] is None
    assert "bukan konfirmasi banjir" in risk[0]["message"]
    assert client.get("/alerts", headers=login("warga1")).json() == []

    _observe(client, login, sid, 158)  # masih di atas ambang -> tidak mengulang notifikasi
    assert len([a for a in client.get("/alerts", headers=login("koord_rw01")).json() if a["kind"] == "risiko"]) == 1
    assert client.get("/incidents", headers=login("koord_rw01")).json() == []


# FR-016 / FR-024: indikasi sensor kebakaran dari pos pantau
def test_sensor_fire_indication(client, login, report):
    r = report("pospantau1", hazard="kebakaran", fire_indicator="panas", from_sensor=True, source_mode="simulation")
    detail = client.get(f"/reports/{r['id']}", headers=login("koord_rw01")).json()
    assert detail["source"] == "sensor"
    assert detail["source_mode"] == "simulation"
    assert detail["fire_indicator"] == "panas"


def test_only_pos_pantau_can_send_sensor_indication(report):
    report("warga1", hazard="kebakaran", from_sensor=True, expect=403)


def test_coordinator_creates_station_with_valid_thresholds(client, login, ids):
    body = {"name": "Pos Baru", "region_id": ids["RT 02 / RW 01"], "lat": -6.89, "lng": 107.61,
            "warning_cm": 200, "danger_cm": 150}
    assert client.post("/stations", json=body, headers=login("koord_rw01")).status_code == 422
    body["danger_cm"] = 300
    r = client.post("/stations", json=body, headers=login("koord_rw01"))
    assert r.status_code == 201 and r.json()["status"] == "tidak_ada_data"
    body["region_id"] = ids["RT 01 / RW 02"]
    assert client.post("/stations", json=body, headers=login("koord_rw01")).status_code == 403
    assert client.post("/stations", json=body, headers=login("pospantau1")).status_code == 403
