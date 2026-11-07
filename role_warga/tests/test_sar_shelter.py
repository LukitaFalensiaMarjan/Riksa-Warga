"""PRD v2: Tim SAR menerima tugas + laporan pasca-bantuan; shelter penuh memberi kabar dan mengarahkan ke alternatif."""
from sqlalchemy import select

from app.models import Alert, AlertDelivery, AlertKind, AuditLog, Shelter, ShelterStatus
from app.services import notifier


def _task(client, login, ids, **extra):
    body = {"task_type": "evakuasi", "priority": "kritis", "description": "Jemput dengan kursi roda",
            "resident_id": ids["Mbah Sutini"], "assignee_id": ids["sar1"], **extra}
    r = client.post("/tasks", json=body, headers=login("koord_rw01"))
    assert r.status_code == 201, r.text
    return r.json()


def _st(client, login, tid, status, user="sar1", **kw):
    return client.post(f"/tasks/{tid}/status", json={"status": status, **kw}, headers=login(user))


REPORT = {"people_helped": 2, "condition": "selamat", "destination": "Sasana Budaya Ganesha (Sabuga ITB)",
          "obstacles": "Jalan tergenang setinggi lutut", "notes": "Dievakuasi dengan 2 pendamping"}


# ---------- Tim SAR ----------
def test_sar_report_after_assistance(client, login, ids, db):
    t = _task(client, login, ids)
    h = login("sar1")
    assert client.post(f"/tasks/{t['id']}/report", json=REPORT, headers=h).status_code == 409  # belum ditangani
    for s in ("diterima", "menuju_lokasi", "dalam_penanganan"):
        assert _st(client, login, t["id"], s).status_code == 200
    r = client.post(f"/tasks/{t['id']}/report", json=REPORT, headers=h)
    assert r.status_code == 201 and r.json()["people_helped"] == 2 and r.json()["created_by"] == ids["sar1"]
    assert _st(client, login, t["id"], "selesai", note="Dievakuasi", people_count=2).status_code == 200
    assert client.post(f"/tasks/{t['id']}/report", json={**REPORT, "condition": "butuh_rujukan"}, headers=h).status_code == 201
    # hak akses
    assert client.post(f"/tasks/{t['id']}/report", json=REPORT, headers=login("sar2")).status_code == 403
    assert client.post(f"/tasks/{t['id']}/report", json=REPORT, headers=login("koord_rw01")).status_code == 403
    assert client.get(f"/tasks/{t['id']}/reports", headers=login("sar2")).status_code == 403
    for user in ("sar1", "koord_rw01"):  # SAR yang bertugas & koordinator wilayahnya dapat membaca
        assert len(client.get(f"/tasks/{t['id']}/reports", headers=login(user)).json()) == 2
    assert client.get(f"/tasks/{t['id']}/reports", headers=login("koord_rw02")).status_code == 403
    db.expire_all()
    assert "task.report" in set(db.scalars(select(AuditLog.action)))


def test_sar_report_validation(client, login, ids):
    t = _task(client, login, ids)
    for s in ("diterima", "menuju_lokasi", "dalam_penanganan"):
        _st(client, login, t["id"], s)
    h = login("sar1")
    for bad in ({**REPORT, "people_helped": -1}, {**REPORT, "people_helped": 501}, {**REPORT, "condition": "hilang"},
                {"condition": "selamat"}, {**REPORT, "notes": "x" * 2001}):
        assert client.post(f"/tasks/{t['id']}/report", json=bad, headers=h).status_code == 422, bad
    assert client.post("/tasks/9999/report", json=REPORT, headers=h).status_code == 404


def test_failed_task_can_still_be_reported(client, login, ids):
    t = _task(client, login, ids)
    for s in ("diterima", "menuju_lokasi", "dalam_penanganan"):
        _st(client, login, t["id"], s)
    assert _st(client, login, t["id"], "gagal", note="Jalan terputus").status_code == 200
    r = client.post(f"/tasks/{t['id']}/report", json={**REPORT, "people_helped": 0, "condition": "lainnya"},
                    headers=login("sar1"))
    assert r.status_code == 201


def test_new_task_notifies_sar_by_telegram_and_sms_without_resident_details(client, login, ids, set_chat, set_phone,
                                                                           monkeypatch):
    set_chat("sar1", "6001")
    set_phone("sar1", "+628116001")
    sent = []
    monkeypatch.setattr(notifier, "send_telegram", lambda chat, text: sent.append(("telegram", chat, text)))
    monkeypatch.setattr(notifier, "send_sms", lambda phone, text: sent.append(("sms", phone, text)))
    _task(client, login, ids)
    assert [(c, to) for c, to, _ in sent] == [("telegram", "6001"), ("sms", "+628116001")]
    assert all("TUGAS BARU" in text and "Mbah Sutini" not in text and "kursi roda" not in text for _, _, text in sent)


# ---------- shelter penuh ----------
def _contacts(set_chat, set_phone):
    for user, n in (("warga1", 1), ("warga3", 3), ("koord_rw01", 4), ("pospantau2", 5), ("sar1", 6), ("admin", 9)):
        set_chat(user, f"100{n}")
        set_phone(user, f"+62811000{n}")


def _recipients(db, channel):
    db.expire_all()
    return {d.recipient for d in db.scalars(select(AlertDelivery).where(AlertDelivery.channel == channel))}


def test_full_shelter_notifies_sar_residents_and_pos_pantau_with_alternative(client, login, ids, db, set_chat, set_phone):
    _contacts(set_chat, set_phone)
    h = login("koord_rw01")
    r = client.post(f"/shelters/{ids['Sasana Budaya Ganesha (Sabuga ITB)']}/status", json={"status": "penuh"}, headers=h)
    assert r.status_code == 200
    db.expire_all()
    alert = db.scalar(select(Alert).where(Alert.kind == AlertKind.SHELTER))
    assert alert.sms and not alert.internal
    assert "SHELTER PENUH" in alert.message and "Sasana Budaya Ganesha (Sabuga ITB)" in alert.message
    assert "Masjid Salman ITB" in alert.message  # alternatif terverifikasi terdekat yang masih tersedia
    assert "Taman Gasibu" not in alert.message  # shelter belum terverifikasi tidak direkomendasikan
    expected = {"1001", "1003", "1004", "1005", "1006"}  # warga, koordinator, pos pantau, Tim SAR; bukan admin (1009)
    assert _recipients(db, "telegram") == expected
    assert _recipients(db, "sms") == {f"+62811000{n}" for n in (1, 3, 4, 5, 6)}
    # status yang sama / kembali tersedia tidak mengirim ulang
    client.post(f"/shelters/{ids['Sasana Budaya Ganesha (Sabuga ITB)']}/status", json={"status": "penuh"}, headers=h)
    client.post(f"/shelters/{ids['Sasana Budaya Ganesha (Sabuga ITB)']}/status", json={"status": "tersedia"}, headers=h)
    db.expire_all()
    assert len(db.scalars(select(Alert).where(Alert.kind == AlertKind.SHELTER)).all()) == 1
    assert client.post(f"/shelters/{ids['Sasana Budaya Ganesha (Sabuga ITB)']}/status", json={"status": "tidak_dapat_digunakan"},
                       headers=h).status_code == 200
    db.expire_all()
    last = db.scalars(select(Alert).where(Alert.kind == AlertKind.SHELTER).order_by(Alert.id.desc())).first()
    assert "TIDAK DAPAT DIGUNAKAN" in last.message


def test_full_shelter_is_not_recommended_anymore(client, login, ids):
    h = login("warga1")
    before = {s["name"]: s for s in client.get("/shelters", headers=h).json()}
    assert before["Sasana Budaya Ganesha (Sabuga ITB)"]["status"] == "tersedia"
    client.post(f"/shelters/{ids['Sasana Budaya Ganesha (Sabuga ITB)']}/status", json={"status": "penuh"}, headers=login("koord_rw01"))
    after = {s["name"]: s for s in client.get("/shelters", headers=h).json()}
    assert after["Sasana Budaya Ganesha (Sabuga ITB)"]["status"] == "penuh"  # tampil sebagai penuh, bukan dihapus diam-diam
    from app.services.evacuation import nearest_shelter
    # rekomendasi terdekat dari dekat Masjid beralih ke shelter lain yang tersedia
    shelters = [Shelter(id=1, name="A", lat=-6.885, lng=107.608, is_verified=True, status=ShelterStatus.PENUH),
                Shelter(id=2, name="B", lat=-6.895, lng=107.620, is_verified=True, status=ShelterStatus.TERSEDIA)]
    assert nearest_shelter(shelters, -6.885, 107.608)[0].name == "B"


def test_checkin_that_fills_a_shelter_triggers_the_alert(client, login, ids, db, set_chat, set_phone):
    _contacts(set_chat, set_phone)
    db.get(Shelter, ids["PUSDAI Jawa Barat"]).capacity = 2
    db.commit()
    r = client.post(f"/shelters/{ids['PUSDAI Jawa Barat']}/checkin", json={"name": "Keluarga A", "people_count": 2},
                    headers=login("sar1"))
    assert r.status_code == 201
    db.expire_all()
    alert = db.scalar(select(Alert).where(Alert.kind == AlertKind.SHELTER))
    assert alert is not None and "PUSDAI Jawa Barat" in alert.message and "SHELTER PENUH" in alert.message
    assert "Stadion Siliwangi" in alert.message  # alternatif terdekat
    assert "1001" in _recipients(db, "telegram")


def test_coordinator_lists_sar_teams_without_reading_all_accounts(client, login, ids):
    r = client.get("/tasks/assignees", headers=login("koord_rw01"))
    assert r.status_code == 200 and {u["name"] for u in r.json()} == {"Tim SAR Satu", "Tim SAR Dua"}
    assert set(r.json()[0]) == {"id", "name"}  # tanpa username/kontak
    for user in ("warga1", "sar1", "pospantau1", "admin"):
        assert client.get("/tasks/assignees", headers=login(user)).status_code == 403
    assert client.get("/users", headers=login("koord_rw01")).status_code == 403
