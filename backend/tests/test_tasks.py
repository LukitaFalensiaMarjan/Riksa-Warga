"""Relawan & penugasan (FR-070–074) + check-in shelter (FR-067)."""
from sqlalchemy import select

from app.models import AuditLog


def _task(client, login, ids, **extra):
    body = {"task_type": "evakuasi", "priority": "kritis", "description": "Jemput dengan kursi roda",
            "resident_id": ids["Mbah Sutini"], "assignee_id": ids["relawan1"], **extra}
    r = client.post("/tasks", json=body, headers=login("koord_rw01"))
    assert r.status_code == 201, r.text
    return r.json()


def _status(client, login, task_id, status, user="relawan1", **extra):
    return client.post(f"/tasks/{task_id}/status", json={"status": status, **extra}, headers=login(user))


def test_full_task_flow_updates_resident_and_shelter(client, login, ids):
    t = _task(client, login, ids, shelter_id=ids["Masjid Al-Ikhlas"])
    assert t["status"] == "menunggu_penerimaan"
    assert t["lat"] is not None  # diambil dari lokasi rumah warga
    assert t["resident_vulnerability"] == ["lansia", "disabilitas"]
    assert _status(client, login, t["id"], "selesai", note="x" * 5).status_code == 409  # tidak boleh lompat
    assert _status(client, login, t["id"], "diterima").status_code == 200
    h = login("koord_rw01")
    res = client.get(f"/residents/{ids['Mbah Sutini']}", headers=h).json()
    assert res["latest_status"] == "dalam_penanganan"
    assert _status(client, login, t["id"], "menuju_lokasi").status_code == 200
    assert _status(client, login, t["id"], "dalam_penanganan").status_code == 200
    assert _status(client, login, t["id"], "selesai").status_code == 422  # hasil wajib
    r = _status(client, login, t["id"], "selesai", note="Dievakuasi dengan 2 pendamping", people_count=2)
    assert r.status_code == 200 and r.json()["result"] == "Dievakuasi dengan 2 pendamping"
    res = client.get(f"/residents/{ids['Mbah Sutini']}", headers=h).json()
    assert res["latest_status"] == "tiba_di_titik_aman"
    shelters = {s["name"]: s for s in client.get("/shelters", headers=h).json()}
    assert shelters["Masjid Al-Ikhlas"]["occupancy"] == 2
    assert _status(client, login, t["id"], "gagal", note="tes").status_code == 409  # sudah final


def test_volunteer_sees_only_own_tasks(client, login, ids):
    mine = _task(client, login, ids)
    other = _task(client, login, ids, assignee_id=ids["relawan2"], resident_id=ids["Pak Darto"])
    seen = {t["id"] for t in client.get("/tasks", headers=login("relawan1")).json()}
    assert seen == {mine["id"]}
    assert client.get(f"/tasks/{other['id']}", headers=login("relawan1")).status_code == 403
    assert _status(client, login, other["id"], "diterima").status_code == 403
    assert client.get("/tasks", headers=login("warga1")).status_code == 403
    assert client.post("/tasks", json={"task_type": "medis", "description": "tes", "region_id": ids["RW 01"]},
                       headers=login("relawan1")).status_code == 403


def test_failed_task_returns_resident_to_queue(client, login, ids):
    t = _task(client, login, ids)
    _status(client, login, t["id"], "diterima")
    assert _status(client, login, t["id"], "gagal").status_code == 422
    assert _status(client, login, t["id"], "gagal", note="Jalan tertutup banjir").status_code == 200
    queue = client.get("/help-requests", headers=login("koord_rw01")).json()
    assert [q["resident"]["name"] for q in queue] == ["Mbah Sutini"]
    assert queue[0]["need_type"] == "evakuasi"


def test_only_coordinator_cancels_and_reassigns(client, login, ids, db):
    t = _task(client, login, ids, assignee_id=None)
    assert t["status"] == "baru"
    assert client.post(f"/tasks/{t['id']}/assign", json={"assignee_id": ids["warga1"]},
                       headers=login("koord_rw01")).status_code == 422  # bukan relawan
    r = client.post(f"/tasks/{t['id']}/assign", json={"assignee_id": ids["relawan2"]}, headers=login("koord_rw01"))
    assert r.json()["status"] == "menunggu_penerimaan" and r.json()["assignee_name"] == "Relawan Dua"
    assert _status(client, login, t["id"], "dibatalkan", user="relawan2", note="tidak bisa").status_code == 403
    r = _status(client, login, t["id"], "dibatalkan", user="koord_rw01", note="Warga sudah dijemput keluarga")
    assert r.status_code == 200
    assert {"task.create", "task.assign", "task.status"} <= set(db.scalars(select(AuditLog.action)))


def test_coordinator_scope_for_tasks(client, login, ids):
    body = {"task_type": "logistik", "description": "Antar air bersih", "resident_id": ids["Bu Rina"]}
    assert client.post("/tasks", json=body, headers=login("koord_rw01")).status_code == 403
    assert client.post("/tasks", json=body, headers=login("koord_rw02")).status_code == 201


def test_manual_checkin_marks_full(client, login, ids):
    h = login("koord_rw02")
    sid = ids["Balai RW 02"]  # kapasitas 80
    r = client.post(f"/shelters/{sid}/checkin", json={"name": "Rombongan RT 02", "people_count": 79}, headers=h)
    assert r.status_code == 201
    client.post(f"/shelters/{sid}/checkin", json={"name": "Bu Rina", "resident_id": ids["Bu Rina"]}, headers=h)
    shelters = {s["name"]: s for s in client.get("/shelters", headers=h).json()}
    assert shelters["Balai RW 02"]["occupancy"] == 80 and shelters["Balai RW 02"]["status"] == "penuh"
    assert client.get(f"/residents/{ids['Bu Rina']}", headers=h).json()["latest_status"] == "tiba_di_titik_aman"
    assert client.post(f"/shelters/{sid}/checkin", json={"name": "x"}, headers=login("warga3")).status_code == 403
