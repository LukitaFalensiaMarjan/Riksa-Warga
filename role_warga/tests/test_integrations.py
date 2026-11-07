"""Integrasi BMKG (prakiraan cuaca -> konteks cuaca mesin aturan) + status sumber (FR-013/014/035)."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db import utcnow
from app.models import AuditLog, IntegrationSource, SourceMode, WeatherContext
from app.services import engine, integrations

HULU_2 = (-6.8812, 107.6106)
HULU_3 = (-6.8798, 107.6095)


def payload(now_tp=12.0, future_tp=0.0, past_tp=0.0):
    t = utcnow().replace(microsecond=0)

    def slot(hours, tp):
        return {"datetime": (t + timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ"), "tp": tp}

    # slot -5 jam sudah lewat, slot -1 jam sedang berlaku (3 jam), slot +2 jam belum berlaku
    return {"data": [{"cuaca": [[slot(-5, past_tp), slot(-1, now_tp), slot(2, future_tp)]]}]}


@pytest.fixture
def bmkg(monkeypatch):
    state = {"payload": payload(), "error": None, "urls": []}

    def fake(url):
        state["urls"].append(url)
        if state["error"]:
            raise state["error"]
        return state["payload"]

    monkeypatch.setattr(integrations, "http_get", fake)
    return state


@pytest.fixture
def src_id(db):
    return db.scalar(select(IntegrationSource.id).where(IntegrationSource.kind == "bmkg"))


def sync(client, login, sid, user="admin"):
    return client.post(f"/integrations/{sid}/sync", headers=login(user))


def weather(db, ids):
    db.expire_all()
    return db.scalar(select(WeatherContext).where(WeatherContext.region_id == ids["Kelurahan Demo"]))


def test_sync_activates_weather_context_labeled_forecast(client, login, db, ids, bmkg, src_id):
    r = sync(client, login, src_id)
    assert r.status_code == 200 and r.json()["status"] == "ok" and r.json()["last_error"] is None
    w = weather(db, ids)
    assert w.is_active and w.source_mode == SourceMode.REAL
    assert "prakiraan" in w.description.lower() and "bukan pengamatan" in w.description and "12" in w.description
    assert "adm4=32.73.01.1001" in bmkg["urls"][-1]
    # hujan di bawah ambang -> konteks tidak aktif
    bmkg["payload"] = payload(now_tp=1.0)
    sync(client, login, src_id)
    assert not weather(db, ids).is_active


def test_uses_current_slot_never_future(client, login, db, ids, bmkg, src_id):
    bmkg["payload"] = payload(now_tp=2.0, future_tp=40.0, past_tp=40.0)
    sync(client, login, src_id)
    w = weather(db, ids)
    assert not w.is_active and "2 mm" in w.description  # slot +2 jam (40 mm) dan slot lama (40 mm) diabaikan


def test_expires_by_itself_and_stale_data_is_not_current(client, login, db, ids, bmkg, src_id):
    sync(client, login, src_id)
    region = ids["Kelurahan Demo"]
    assert engine.weather_active(db, region, utcnow(), SourceMode.REAL)
    assert not engine.weather_active(db, region, utcnow() + timedelta(hours=4), SourceMode.REAL)


def test_bmkg_context_drives_flood_siaga_unverified(client, login, report, bmkg, src_id):
    sync(client, login, src_id)
    iid = report("warga1")["incident_id"]
    report("warga2", at=HULU_2)
    report("warga3", at=HULU_3)
    inc = client.get(f"/incidents/{iid}", headers=login("koord_rw01")).json()
    assert inc["level"] == "siaga" and inc["verification"] == "belum_diverifikasi"
    assert "cuaca" in {f["faktor"] for f in inc["reports"][0]["score_factors"]}


def test_failure_marks_status_and_keeps_system_running(client, login, db, ids, bmkg, src_id):
    sync(client, login, src_id)
    bmkg["error"] = OSError("jaringan putus")
    r = sync(client, login, src_id)
    assert r.status_code == 200 and r.json()["status"] == "gagal" and "jaringan putus" in r.json()["last_error"]
    assert weather(db, ids).is_active  # data terakhir tidak dihapus; masa berlakunya yang membatasi
    assert client.get("/dashboard", headers=login("koord_rw01")).status_code == 200
    assert client.get("/alerts", headers=login("warga1")).status_code == 200
    # detail galat & konfigurasi hanya untuk admin
    v = client.get("/integrations", headers=login("koord_rw01")).json()[0]
    assert v["status"] == "gagal" and "last_error" not in v and "config" not in v
    a = client.get("/integrations", headers=login("admin")).json()[0]
    assert "jaringan putus" in a["last_error"] and a["config"]["adm4"] == "32.73.01.1001"
    bmkg["error"] = None  # pulih sendiri
    assert sync(client, login, src_id).json()["status"] == "ok"


def test_bad_payloads_and_config_fail_cleanly(client, login, db, bmkg, src_id):
    for bad, needle in (({"aneh": 1}, "tidak dikenali"), ({"data": [{"cuaca": [[]]}]}, "kosong")):
        bmkg["payload"] = bad
        r = sync(client, login, src_id).json()
        assert r["status"] == "gagal" and needle in r["last_error"]
    future_only = {"data": [{"cuaca": [[{"datetime": (utcnow() + timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ"), "tp": 9}]]}]}
    bmkg["payload"] = future_only
    assert "sedang berlaku" in sync(client, login, src_id).json()["last_error"]
    src = db.get(IntegrationSource, src_id)
    src.config = {}
    db.commit()
    assert "region_id" in sync(client, login, src_id).json()["last_error"]


def test_simulation_weather_is_not_overwritten(client, login, db, ids, bmkg, src_id):
    body = {"region_id": ids["Kelurahan Demo"], "is_active": True, "description": "Hujan simulasi demo",
            "source_mode": "simulation"}
    assert client.put("/weather", json=body, headers=login("pospantau1")).status_code == 200
    bmkg["payload"] = payload(now_tp=0.0)
    assert sync(client, login, src_id).json()["status"] == "ok"
    w = weather(db, ids)
    assert w.source_mode == SourceMode.SIMULATION and w.is_active and w.description == "Hujan simulasi demo"


def test_due_and_sync_due_respect_interval_and_enabled(db, bmkg):
    src = db.scalar(select(IntegrationSource))
    now = utcnow()
    assert integrations.due(src, now)  # belum pernah sinkron
    integrations.sync_due(db, now)
    db.commit()
    db.refresh(src)
    assert src.status == "ok" and not integrations.due(src, now + timedelta(seconds=30))
    assert integrations.due(src, now + timedelta(seconds=src.poll_interval_seconds))
    n = len(bmkg["urls"])
    integrations.sync_due(db, now + timedelta(seconds=30))
    assert len(bmkg["urls"]) == n  # belum jatuh tempo: tidak memanggil BMKG lagi
    src.enabled = False
    assert not integrations.due(src, now + timedelta(days=1))


def test_admin_manages_sources_and_everything_is_audited(client, login, db, ids, bmkg):
    a, k = login("admin"), login("koord_rw01")
    cfg = {"region_id": ids["RW 01"], "adm4": "32.73.01.1002", "rain_mm": 8}
    body = {"name": "BMKG RW 01", "kind": "bmkg", "config": cfg}
    assert client.post("/integrations", json=body, headers=k).status_code == 403
    assert client.post("/integrations", json={**body, "kind": "magma"}, headers=a).status_code == 422
    assert client.post("/integrations", json={**body, "config": {**cfg, "region_id": 9999}}, headers=a).status_code == 422
    assert client.post("/integrations", json={**body, "config": {**cfg, "adm4": "bukan-kode"}}, headers=a).status_code == 422
    assert client.post("/integrations", json={**body, "config": {**cfg, "rain_mm": -1}}, headers=a).status_code == 422
    assert client.post("/integrations", json={**body, "poll_interval_seconds": 5}, headers=a).status_code == 422
    created = client.post("/integrations", json=body, headers=a)
    assert created.status_code == 201 and created.json()["stale"] is True  # belum pernah sukses
    assert client.post("/integrations", json=body, headers=a).status_code == 409
    sid = created.json()["id"]
    assert client.patch(f"/integrations/{sid}", json={"enabled": False, "poll_interval_seconds": 120}, headers=a).status_code == 200
    assert client.patch(f"/integrations/{sid}", json={"poll_interval_seconds": 5}, headers=a).status_code == 422
    assert client.patch("/integrations/9999", json={"enabled": True}, headers=a).status_code == 404
    # koordinator hanya boleh sinkron sumber di wilayahnya
    assert sync(client, login, sid, "pospantau1").status_code == 200  # pos pantau menyinkronkan sumber area-nya
    assert sync(client, login, sid, "koord_rw01").status_code == 403
    assert sync(client, login, sid, "warga1").status_code == 403
    assert sync(client, login, sid).json()["status"] == "ok"
    assert client.get("/integrations", headers=login("warga1")).json()[-1]["stale"] is False
    db.expire_all()
    actions = {e.action for e in db.scalars(select(AuditLog))}
    assert {"integration.create", "integration.update", "integration.sync", "weather.sync"} <= actions
    sys_entry = db.scalars(select(AuditLog).where(AuditLog.action == "weather.sync")).first()
    assert sys_entry.actor_id is None  # pembaruan otomatis dicatat sebagai sistem
