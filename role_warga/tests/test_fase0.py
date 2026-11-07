from sqlalchemy import select

from app.models import AuditLog, Region


def _region_id(db, name: str) -> int:
    return db.scalar(select(Region.id).where(Region.name == name))


# FR-001: login + diarahkan sesuai peran
def test_login_returns_role(client, login):
    r = client.get("/auth/me", headers=login("koord_rw01"))
    assert r.status_code == 200
    assert r.json()["role"] == "koordinator"


def test_login_wrong_password(client):
    r = client.post("/auth/login", json={"username": "warga1", "password": "salah"})
    assert r.status_code == 401


def test_login_rate_limited(client):
    for _ in range(5):
        client.post("/auth/login", json={"username": "warga1", "password": "salah"})
    r = client.post("/auth/login", json={"username": "warga1", "password": "salah"})
    assert r.status_code == 429


def test_unknown_usernames_not_tracked(client):
    from app.routers import auth as auth_router

    for i in range(20):
        client.post("/auth/login", json={"username": f"acak{i}", "password": "x"})
    assert dict(auth_router._fails) == {}


# FR-005: pengguna mengatur kanal kontaknya sendiri
def test_update_own_telegram_profile(client, login, db):
    h = login("koord_rw01")
    r = client.patch("/auth/me", json={"telegram_chat_id": "1949754174", "phone": "0812"}, headers=h)
    assert r.status_code == 200
    assert r.json()["telegram_chat_id"] == "1949754174" and r.json()["phone"] == "0812"
    assert client.patch("/auth/me", json={"telegram_chat_id": "bukan-angka"}, headers=h).status_code == 422
    r = client.patch("/auth/me", json={"telegram_chat_id": ""}, headers=h)  # kosong = hapus; phone tak berubah
    assert r.json()["telegram_chat_id"] is None and r.json()["phone"] == "0812"
    assert "user.profile" in set(db.scalars(select(AuditLog.action)))


def test_region_lookup_covers_whole_kelurahan(client, login):
    names = {x["name"] for x in client.get("/regions/lookup", headers=login("warga1")).json()}
    assert {"RT 01 / RW 01", "RT 01 / RW 02", "RW 02", "Kelurahan Demo"} <= names
    assert "Jawa Barat" not in names  # di atas kelurahan: tidak perlu ditampilkan


def test_ui_is_served_and_api_still_wins(client):
    page = client.get("/")
    assert page.status_code == 200 and "Riksa Warga" in page.text
    assert client.get("/app.js").status_code == 200
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/auth/me").status_code == 401  # rute API tidak tertimpa file statis


def test_no_token_rejected(client):
    assert client.get("/auth/me").status_code == 401


# FR-002: admin buat + nonaktifkan akun, tercatat di audit
def test_admin_creates_and_deactivates_user(client, login, db):
    admin = login("admin")
    body = {"username": "sar9", "name": "SAR Sembilan", "password": "rahasia-123",
            "role": "tim_sar", "region_id": _region_id(db, "RW 02")}
    r = client.post("/users", json=body, headers=admin)
    assert r.status_code == 201
    uid = r.json()["id"]

    r = client.post(f"/users/{uid}/deactivate", json={"reason": "pindah domisili"}, headers=admin)
    assert r.status_code == 200 and r.json()["is_active"] is False

    # akun nonaktif tidak bisa login
    r = client.post("/auth/login", json={"username": "sar9", "password": "rahasia-123"})
    assert r.status_code == 401

    actions = set(db.scalars(select(AuditLog.action)))
    assert {"user.create", "user.deactivate"} <= actions


def test_deactivate_requires_reason(client, login):
    r = client.post("/users/2/deactivate", json={}, headers=login("admin"))
    assert r.status_code == 422


def test_deactivated_token_stops_working(client, login, db):
    token = login("warga2")
    uid = client.get("/auth/me", headers=token).json()["id"]
    client.post(f"/users/{uid}/deactivate", json={"reason": "tes"}, headers=login("admin"))
    assert client.get("/auth/me", headers=token).status_code == 401


# FR-004: RBAC
def test_non_admin_cannot_create_user(client, login, db):
    body = {"username": "x_user", "name": "X", "password": "rahasia-123",
            "role": "admin", "region_id": _region_id(db, "RW 01")}
    for u in ("warga1", "koord_rw01", "sar1"):
        assert client.post("/users", json=body, headers=login(u)).status_code == 403


def test_warga_cannot_list_users(client, login):
    assert client.get("/users", headers=login("warga1")).status_code == 403


# FR-003 + FR-004: pembatasan wilayah
def test_coordinator_sees_only_own_region_tree(client, login, db):
    r = client.get("/regions", headers=login("koord_rw01"))
    names = {x["name"] for x in r.json()}
    assert names == {"RW 01", "RT 01 / RW 01", "RT 02 / RW 01"}


def test_coordinator_blocked_from_other_rw(client, login, db):
    other = _region_id(db, "RT 01 / RW 02")
    assert client.get(f"/regions/{other}", headers=login("koord_rw01")).status_code == 403
    own = _region_id(db, "RT 02 / RW 01")
    assert client.get(f"/regions/{own}", headers=login("koord_rw01")).status_code == 200


def test_only_admin_manages_users(client, login):  # PRD v2: admin = kelola pengguna
    for user in ("koord_rw02", "pospantau1", "sar1", "warga1"):
        assert client.get("/users", headers=login(user)).status_code == 403, user
    assert len(client.get("/users", headers=login("admin")).json()) == 10


def test_admin_sees_all_regions(client, login):
    assert len(client.get("/regions", headers=login("admin")).json()) == 10
