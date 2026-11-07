"""Fitur Koordinator RT/RW: verifikasi laporan, data warga, status warga, shelter, cuaca, aturan, dashboard."""
from sqlalchemy import select

from app.models import AuditLog
from conftest import HILIR


# FR-032
def test_verify_and_reject_report(client, login, report, db):
    a = report("warga1")
    b = report("warga2")
    h = login("pospantau1")  # PRD v2: verifikasi laporan oleh pos pantau
    v = client.post(f"/reports/{a['id']}/verify", json={"note": "Dicek via telepon"}, headers=h)
    assert v.status_code == 200 and v.json()["status"] == "terverifikasi"
    assert v.json()["reviewed_by"] is not None
    assert client.post(f"/reports/{b['id']}/reject", json={}, headers=h).status_code == 422  # alasan wajib
    r = client.post(f"/reports/{b['id']}/reject", json={"reason": "Lokasi bukan di sungai"}, headers=h)
    assert r.status_code == 200
    assert client.post(f"/reports/{b['id']}/verify", json={}, headers=h).status_code == 409
    mine = client.get("/reports/mine", headers=login("warga2")).json()[0]
    assert mine["status"] == "ditolak" and mine["status_reason"] == "Lokasi bukan di sungai"
    actions = set(db.scalars(select(AuditLog.action)))
    assert {"report.verify", "report.reject"} <= actions


def test_only_pos_pantau_reviews_reports(client, login, report):
    r = report("warga3", at=HILIR)
    for user in ("koord_rw01", "koord_rw02", "warga1", "sar1", "admin"):  # bukan pos pantau
        assert client.post(f"/reports/{r['id']}/verify", json={}, headers=login(user)).status_code == 403, user
    assert client.get("/reports", headers=login("koord_rw01")).status_code == 403
    # pos pantau memeriksa satu kelurahan (RW 01 maupun RW 02)
    assert client.post(f"/reports/{r['id']}/verify", json={}, headers=login("pospantau1")).status_code == 200


# FR-030
def test_score_factors_visible(client, login, report):
    r = report("pospantau1")
    detail = client.get(f"/reports/{r['id']}", headers=login("pospantau1")).json()
    names = {f["faktor"] for f in detail["score_factors"]}
    assert {"dasar", "hulu", "sumber_petugas"} <= names
    assert detail["score"] == sum(f["poin"] for f in detail["score_factors"])


# FR-060, FR-061
def test_resident_crud_and_scope(client, login, ids):
    h = login("koord_rw01")
    body = {"name": "Pak Ujang", "region_id": ids["RT 01 / RW 01"], "has_smartphone": False,
            "vulnerability": ["lansia"], "assistance_notes": "Butuh tongkat"}
    assert client.post("/residents", json=body, headers=h).status_code == 422  # tanpa consent
    body["consent"] = True
    r = client.post("/residents", json=body, headers=h)
    assert r.status_code == 201
    assert r.json()["latest_status"] == "belum_terkonfirmasi"
    rid = r.json()["id"]
    p = client.patch(f"/residents/{rid}", json={"phone": "08123"}, headers=h)
    assert p.status_code == 200 and p.json()["phone"] == "08123"

    body["region_id"] = ids["RT 01 / RW 02"]
    assert client.post("/residents", json=body, headers=h).status_code == 403
    assert client.get(f"/residents/{ids['Bu Rina']}", headers=h).status_code == 403

    names = {x["name"] for x in client.get("/residents", headers=h).json()}
    assert "Bu Rina" not in names and "Pak Ujang" in names
    vulnerable = {x["name"] for x in client.get("/residents?vulnerable=true", headers=h).json()}
    assert vulnerable == {"Mbah Sutini", "Pak Darto", "Pak Ujang"}


def test_sensitive_notes_only_in_audited_detail(client, login, ids, db):
    h = login("koord_rw01")
    listing = {x["name"]: x for x in client.get("/residents", headers=h).json()}
    assert "assistance_notes" not in listing["Mbah Sutini"]
    detail = client.get(f"/residents/{ids['Mbah Sutini']}", headers=h).json()
    assert "kursi roda" in detail["assistance_notes"]
    logged = db.scalars(select(AuditLog).where(AuditLog.action == "resident.view_detail")).all()
    assert [(l.actor_id, l.entity_id) for l in logged] == [(ids["koord_rw01"], str(ids["Mbah Sutini"]))]
    create_logs = db.scalars(select(AuditLog).where(AuditLog.action == "resident.create")).all()
    assert all("kursi" not in str(l.new_value) for l in create_logs)


# FR-064, FR-065
def test_status_for_resident_without_smartphone(client, login, ids):
    h = login("koord_rw01")
    rid = ids["Mbah Sutini"]
    bad = client.post(f"/residents/{rid}/status", json={"status": "aman_terverifikasi"}, headers=h)
    assert bad.status_code == 422  # metode verifikasi wajib dicatat
    assert client.post(f"/residents/{rid}/status", json={"status": "aman_mandiri"}, headers=h).status_code == 422
    r = client.post(f"/residents/{rid}/status",
                    json={"status": "butuh_bantuan", "source": "buddy", "need_type": "evakuasi"}, headers=h)
    assert r.status_code == 201 and r.json()["source"] == "buddy"
    client.post(f"/residents/{rid}/status", json={"status": "dalam_penanganan", "note": "Dijemput tim RT"}, headers=h)
    client.post(f"/residents/{rid}/status",
                json={"status": "tiba_di_titik_aman", "note": "Sasana Budaya Ganesha (Sabuga ITB)"}, headers=h)
    history = client.get(f"/residents/{rid}/statuses", headers=h).json()
    assert [x["status"] for x in history] == ["butuh_bantuan", "dalam_penanganan", "tiba_di_titik_aman"]


def test_summary_counts_unconfirmed(client, login, ids):
    h = login("koord_rw01")
    client.post("/me/status", json={"status": "aman"}, headers=login("warga1"))
    s = client.get("/residents/summary", headers=h).json()
    assert s["total"] == 4  # warga RW 01
    assert s["by_status"]["aman_mandiri"] == 1
    assert s["by_status"]["belum_terkonfirmasi"] == 3
    assert s["by_status"]["aman_terverifikasi"] == 0


def test_help_queue_prioritizes_vulnerable(client, login, ids):
    client.post("/me/status", json={"status": "butuh_bantuan", "need_type": "logistik"}, headers=login("warga1"))
    client.post(f"/residents/{ids['Pak Darto']}/status",
                json={"status": "butuh_bantuan", "need_type": "medis", "source": "keluarga"},
                headers=login("koord_rw01"))
    queue = client.get("/help-requests", headers=login("koord_rw01")).json()
    assert [q["resident"]["name"] for q in queue] == ["Pak Darto", "Warga Satu"]
    assert queue[0]["is_vulnerable"] is True
    assert client.get("/help-requests", headers=login("koord_rw02")).json() == []


# FR-051, FR-054
def test_shelter_management(client, login, ids, db):
    h = login("koord_rw01")
    body = {"name": "SD Demo", "region_id": ids["RT 02 / RW 01"], "lat": -6.886, "lng": 107.609,
            "address": "Jl. Sekolah 3", "capacity": 60}
    s = client.post("/shelters", json=body, headers=h).json()
    assert s["is_verified"] is False and s["status"] == "tersedia"
    assert "SD Demo" not in {x["name"] for x in client.get("/shelters", headers=login("warga1")).json()}
    client.post(f"/shelters/{s['id']}/verify", json={"note": "Dicek ketua RT"}, headers=h)
    assert "SD Demo" in {x["name"] for x in client.get("/shelters", headers=login("warga1")).json()}
    r = client.post(f"/shelters/{s['id']}/status", json={"status": "penuh"}, headers=h)
    assert r.json()["status"] == "penuh"
    assert client.post(f"/shelters/{ids['PUSDAI Jawa Barat']}/status", json={"status": "penuh"},
                       headers=h).status_code == 403
    assert "shelter.status" in set(db.scalars(select(AuditLog.action)))


# FR-034
def test_rules_readable_and_admin_only_update(client, login):
    rules = {r["hazard"]: r for r in client.get("/rules", headers=login("koord_rw01")).json()}
    assert rules["banjir"]["params"]["siaga_min_reporters"] == 3
    assert rules["banjir"]["is_default"] is True
    params = dict(rules["banjir"]["params"], waspada_timeout_minutes=1)
    assert client.put("/rules/banjir", json=params, headers=login("koord_rw01")).status_code == 403
    assert client.put("/rules/banjir", json=dict(params, siaga_min_reporters=1),
                      headers=login("admin")).status_code == 422
    r = client.put("/rules/banjir", json=params, headers=login("admin"))
    assert r.status_code == 200 and r.json()["is_default"] is False
    assert client.get("/rules", headers=login("koord_rw01")).json()[0]["params"]["waspada_timeout_minutes"] == 1


def test_weather_scope(client, login, ids):
    body = {"region_id": ids["RW 01"], "is_active": True, "description": "Peringatan hujan lebat BMKG",
            "source_mode": "simulation"}
    assert client.put("/weather", json=body, headers=login("koord_rw01")).status_code == 200
    body["region_id"] = ids["RW 02"]
    assert client.put("/weather", json=body, headers=login("koord_rw01")).status_code == 403
    assert client.put("/weather", json=body, headers=login("warga1")).status_code == 403
    assert len(client.get("/weather", headers=login("warga1")).json()) == 1


# FR-010, FR-011
def test_dashboard_summary(client, login, report, ids):
    client.post(f"/stations/{ids['Pos Pantau Hulu']}/observations", json={"level_cm": 90, "source_mode": "simulation"},
                headers=login("pospantau1"))
    report("warga1")
    report("warga2")
    report("pospantau1", source_mode="simulation")  # simulasi jadi kejadian terpisah
    d = client.get("/dashboard", headers=login("koord_rw01")).json()
    assert len(d["incidents"]) == 2
    real = next(i for i in d["incidents"] if not i["is_simulation"])
    assert real["unique_reporters"] == 2 and "pending_deadline" in real
    assert d["reports_24h"]["total"] == 3
    assert d["reports_24h"]["by_mode"] == {"real": 2, "simulation": 1}
    station = next(s for s in d["stations"] if s["name"] == "Pos Pantau Hulu")
    assert station["latest"]["source_mode"] == "simulation" and station["status"] == "normal"
    assert d["residents"]["incident_id"] == d["incidents"][0]["id"]
    assert d["residents"]["by_status"]["belum_terkonfirmasi"] == 4
    assert {a["kind"] for a in d["recent_alerts"]} == {"pantau", "usulan"}
