"""Fitur Warga: laporan, foto, status laporan, Saya Aman/Butuh Bantuan, alert, shelter."""
from conftest import HILIR, PNG


# FR-020, FR-022, FR-027
def test_warga_creates_flood_report_and_sees_status(client, login, report):
    r = report("warga1", gps_lat=-6.8806, gps_lng=107.6103)
    assert r["status"] == "diterima"
    assert r["incident_id"] is not None
    mine = client.get("/reports/mine", headers=login("warga1")).json()
    assert [m["id"] for m in mine] == [r["id"]]
    assert "score_factors" not in mine[0]  # detail skor hanya untuk koordinator


def test_report_validation(report):
    report("warga1", hazard="kebakaran", expect=422)  # hanya banjir yang didukung
    report("warga1", at=(-95, 107.6), expect=422)
    report("warga1", gps_lat=-6.88, expect=422)  # gps harus berpasangan
    report("warga1", description="ok", expect=422)
    report("warga1", reported_at="2099-01-01T00:00:00Z", expect=422)
    report("warga1", reported_at="2026-11-07T14:00:00", expect=422)  # tanpa zona waktu
    report("warga1", region_id=None, expect=422)  # lokasi kejadian wajib


# Lokasi kejadian menentukan wilayah kejadian & audiens alert, bukan alamat pelapor
def test_report_uses_event_region_not_reporter_home(client, login, report, ids):
    r = report("warga1", at=HILIR, region_id=ids["RT 01 / RW 02"])
    iid = r["incident_id"]
    assert client.get(f"/incidents/{iid}", headers=login("koord_rw01")).status_code == 403
    alert = client.post(f"/incidents/{iid}/level", json={"level": "waspada", "reason": "Air naik terlihat dari pos"},
                        headers=login("pospantau2")).json()
    assert alert["audience_region_id"] == ids["Kelurahan Demo"]  # banjir: audiens sekelurahan dari wilayah kejadian
    assert client.get("/alerts", headers=login("warga3")).json()  # warga RW 02 menerima


# FR-021
def test_photo_upload_rules(client, login, report):
    rid = report("warga1")["id"]
    h = login("warga1")
    bad = client.post(f"/reports/{rid}/photo", files={"file": ("x.jpg", b"bukan gambar", "image/jpeg")}, headers=h)
    assert bad.status_code == 415  # isi file dicek, bukan ekstensi
    big = PNG + b"\x00" * (5 * 1024 * 1024)
    assert client.post(f"/reports/{rid}/photo", files={"file": ("b.png", big, "image/png")},
                       headers=h).status_code == 413
    other = client.post(f"/reports/{rid}/photo", files={"file": ("a.png", PNG, "image/png")},
                        headers=login("warga2"))
    assert other.status_code == 403
    ok = client.post(f"/reports/{rid}/photo", files={"file": ("a.png", PNG, "image/png")}, headers=h)
    assert ok.status_code == 200 and ok.json()["has_photo"] is True
    again = client.post(f"/reports/{rid}/photo", files={"file": ("a.png", PNG, "image/png")}, headers=h)
    assert again.status_code == 409
    img = client.get(f"/reports/{rid}/photo", headers=h)
    assert img.status_code == 200 and img.content == PNG


# PRD §21.1 langkah 13: foto lama dipakai ulang -> ditandai, tidak dihitung
def test_reused_photo_flagged_and_not_counted(client, login, report):
    first = report("warga1")["id"]
    client.post(f"/reports/{first}/photo", files={"file": ("a.png", PNG, "image/png")}, headers=login("warga1"))
    second = report("warga2")["id"]
    client.post(f"/reports/{second}/photo", files={"file": ("a.png", PNG, "image/png")}, headers=login("warga2"))
    detail = client.get(f"/reports/{second}", headers=login("pospantau1")).json()
    assert "foto_pernah_dipakai" in detail["flags"]
    incident = client.get(f"/incidents/{detail['incident_id']}", headers=login("pospantau1")).json()
    assert incident["unique_reporters"] == 1
    assert incident["pending_level"] is None


# PRD §16.3 perlindungan spam
def test_report_rate_limit(report):
    for _ in range(10):
        report("warga1")
    report("warga1", expect=429)


# FR-026 laporan bernilai rendah/duplikat tetap tersimpan
def test_duplicate_report_kept(client, login, report):
    a = report("warga1")
    b = report("warga1")
    mine = {m["id"]: m for m in client.get("/reports/mine", headers=login("warga1")).json()}
    assert mine[b["id"]]["status"] == "duplikat"
    assert mine[a["id"]]["status"] == "diterima"


# FR-062
def test_saya_aman_is_self_report_not_verified(client, login, ids):
    r = client.post("/me/status", json={"status": "aman"}, headers=login("warga1"))
    assert r.status_code == 201
    assert r.json()["status"] == "aman_mandiri" and r.json()["source"] == "mandiri"
    me = client.get("/me/resident", headers=login("warga1")).json()
    assert me["latest_status"] == "aman_mandiri"
    residents = {x["name"]: x for x in client.get("/residents", headers=login("koord_rw01")).json()}
    assert residents["Warga Satu"]["latest_status"] == "aman_mandiri"


# FR-063
def test_butuh_bantuan_enters_help_queue(client, login, report):
    incident_id = report("warga2")["incident_id"]
    h = login("warga1")
    assert client.post("/me/status", json={"status": "butuh_bantuan"}, headers=h).status_code == 422
    r = client.post("/me/status", json={"status": "butuh_bantuan", "need_type": "evakuasi", "note": "Air masuk rumah"},
                    headers=h)
    assert r.status_code == 201
    assert r.json()["incident_id"] == incident_id  # otomatis terhubung ke kejadian aktif di kelurahannya
    queue = client.get("/help-requests", headers=login("koord_rw01")).json()
    assert [q["resident"]["name"] for q in queue] == ["Warga Satu"]
    assert queue[0]["need_type"] == "evakuasi"


def test_status_for_user_without_resident_record(client, login, ids):
    body = {"username": "warga9", "name": "Warga Baru", "password": "rahasia-123", "role": "warga",
            "region_id": ids["RT 01 / RW 01"]}
    assert client.post("/users", json=body, headers=login("admin")).status_code == 201
    token = client.post("/auth/login", json={"username": "warga9", "password": "rahasia-123"}).json()["access_token"]
    r = client.post("/me/status", json={"status": "aman"}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 201  # data warga dibuat otomatis dari akun


# RBAC: warga hanya melihat alert publik wilayahnya
def test_warga_sees_public_alerts_only(client, login, report, ids):
    incident_id = report("warga1")["incident_id"]
    assert client.get("/alerts", headers=login("warga1")).json() == []  # Pantau = internal
    client.post(f"/incidents/{incident_id}/level", json={"level": "waspada", "reason": "Dicek langsung ke lokasi"},
                headers=login("pospantau1"))
    alerts = client.get("/alerts", headers=login("warga1")).json()
    assert [a["kind"] for a in alerts] == ["level"]
    assert alerts[0]["internal"] is False
    assert client.get("/alerts", headers=login("warga3")).json()  # RW 02 sekelurahan ikut menerima (banjir)


def test_warga_sees_only_verified_shelters(client, login):
    names = {s["name"] for s in client.get("/shelters", headers=login("warga1")).json()}
    from scripts.seed import SHELTERS
    assert names == {s[0] for s in SHELTERS if s[6]}  # semua kecuali yang belum terverifikasi
    assert "Taman Gasibu" not in names


def test_warga_blocked_from_coordinator_features(client, login, report):
    r = report("warga1", at=HILIR)
    h = login("warga1")
    for path in ("/residents", "/incidents", "/dashboard", "/reports", "/help-requests", "/rules"):
        assert client.get(path, headers=h).status_code == 403, path
    assert client.post(f"/reports/{r['id']}/verify", json={}, headers=h).status_code == 403
    assert client.get(f"/reports/{r['id']}", headers=login("warga2")).status_code == 403


def test_report_title_and_water_condition(client, login, report):
    r = report("warga1", title="Air Cikapundung naik", water_condition="meluap")
    assert r["title"] == "Air Cikapundung naik" and r["water_condition"] == "meluap"
    mine = client.get("/reports/mine", headers=login("warga1")).json()[0]
    assert mine["title"] == "Air Cikapundung naik" and mine["water_condition"] == "meluap"
    report("warga1", water_condition="tsunami", expect=422)  # di luar kategori
    report("warga1", title="x", expect=422)  # judul terlalu pendek
