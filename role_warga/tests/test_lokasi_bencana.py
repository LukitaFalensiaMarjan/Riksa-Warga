"""PRD v2 §8-§9: izin lokasi sekali, Mode Bencana, Diduga Butuh Bantuan, peta Tim SAR, retensi lokasi."""
from datetime import timedelta

from sqlalchemy import select

from app.config import settings
from app.db import utcnow
from app.models import Alert, AlertDelivery, AlertKind, AuditLog, ResidentStatusLog, RiverStatusLog, SafetyStatus
from app.services import disaster, notifier
from conftest import HILIR, HULU


def _river(client, login, ids, status="meluap", station="Pos Pantau Hulu"):
    r = client.post(f"/stations/{ids[station]}/condition", json={"status": status}, headers=login("pospantau1"))
    assert r.status_code == 201, r.text


def _share(client, login, user, at):
    assert client.post("/me/location-consent", headers=login(user)).status_code == 201
    assert client.post("/me/location", json={"lat": at[0], "lng": at[1]}, headers=login(user)).status_code == 200


def _duga(db, now):
    db.expire_all()
    return [(r.resident_id, r.source) for r in db.scalars(
        select(ResidentStatusLog).where(ResidentStatusLog.status == SafetyStatus.DUGA_BUTUH_BANTUAN))]


# ---------- izin lokasi ----------
def test_consent_is_asked_once_and_can_be_revoked(client, login):
    h = login("warga1")
    first = client.get("/me/location-consent", headers=h).json()
    assert first["granted"] is False and first["disaster_mode"]["active"] is False
    assert client.post("/me/location", json={"lat": -6.88, "lng": 107.61}, headers=h).status_code == 403  # belum izin
    granted = client.post("/me/location-consent", headers=h).json()
    assert granted["granted"] is True and granted["granted_at"]
    assert client.post("/me/location-consent", headers=h).json()["granted_at"] == granted["granted_at"]  # sekali saja
    assert client.post("/me/location", json={"lat": -6.88, "lng": 107.61}, headers=h).json()["last_lat"] == -6.88
    revoked = client.delete("/me/location-consent", headers=h).json()
    assert revoked["granted"] is False and revoked["revoked_at"]
    assert client.get("/me/resident", headers=h).json()["last_lat"] is None  # lokasi terkini ikut dihapus
    assert client.post("/me/location", json={"lat": -6.88, "lng": 107.61}, headers=h).status_code == 403
    assert client.post("/me/location-consent", headers=h).json()["granted"] is True  # dapat memberi izin lagi


def test_status_location_is_ignored_without_consent(client, login):
    h = login("warga2")
    r = client.post("/me/status", json={"status": "butuh_bantuan", "need_type": "medis", "lat": -6.88, "lng": 107.61}, headers=h)
    assert r.status_code == 201 and r.json()["lat"] is None  # status tercatat, lokasi tidak disimpan
    assert client.get("/me/resident", headers=h).json()["last_lat"] is None


# ---------- Mode Bencana ----------
def test_disaster_mode_follows_river_overflow_and_announcements(client, login, ids, db):
    h = login("warga1")
    mode = lambda: client.get("/me/location-consent", headers=h).json()["disaster_mode"]  # noqa: E731
    assert mode()["active"] is False
    _river(client, login, ids, "waspada")
    assert mode()["active"] is False  # Waspada belum Mode Bencana
    _river(client, login, ids, "meluap")
    m = mode()
    assert m["active"] is True and m["since"] and "Sungai meluap di Pos Pantau Hulu" in m["reasons"][0]
    _river(client, login, ids, "normal")
    assert mode()["active"] is False
    body = {"severity": "meluap", "region_id": ids["Kelurahan Demo"], "summary": "Sungai meluap di hulu",
            "basis_note": "Pengamatan langsung pos hulu"}
    r = client.post("/announcements", json=body, headers=login("pospantau1"))
    assert r.status_code == 201 and mode()["active"] is True  # pengumuman meluap memicu Mode Bencana
    db.expire_all()
    db.get(Alert, r.json()["id"]).created_at = utcnow() - timedelta(hours=settings.announcement_ttl_hours + 1)
    db.commit()
    assert mode()["active"] is False  # masa berlaku habis


def test_live_location_visible_to_coordinator_only_in_disaster(client, login, ids):
    _share(client, login, "warga1", HULU)
    h = login("koord_rw01")
    rid = ids["Warga Satu"]
    assert client.get(f"/residents/{rid}", headers=h).json()["last_lat"] is None  # bukan saat bencana
    _river(client, login, ids)
    assert client.get(f"/residents/{rid}", headers=h).json()["last_lat"] == HULU[0]
    listing = {r["name"]: r for r in client.get("/residents", headers=h).json()}
    assert listing["Warga Satu"]["last_lat"] == HULU[0]


# ---------- Diduga Butuh Bantuan ----------
def test_unanswered_resident_in_danger_zone_becomes_suspected_needing_help(client, login, ids, db, set_chat):
    _share(client, login, "warga2", HULU)  # tidak menjawab, di dalam zona
    _share(client, login, "warga1", HULU)  # menjawab Aman
    _share(client, login, "warga3", HILIR)  # ~2,2 km dari pos hulu: di luar zona (radius 1,5 km)
    for user, chat in (("koord_rw01", "2001"), ("sar1", "6001"), ("warga2", "1002"), ("pospantau1", "5001"), ("admin", "9001")):
        set_chat(user, chat)
    _river(client, login, ids)
    assert client.post("/me/status", json={"status": "aman"}, headers=login("warga1")).status_code == 201
    now = utcnow()
    assert disaster.unconfirmed_tick(db, now + timedelta(minutes=settings.unconfirmed_minutes - 5)) == []  # masih masa tunggu
    assert _duga(db, now) == []
    fired = disaster.unconfirmed_tick(db, now + timedelta(minutes=settings.unconfirmed_minutes + 1))
    db.commit()
    assert [(r, s.value) for r, s in _duga(db, now)] == [(ids["Warga Dua"], "sistem")]  # hanya yang diam di zona
    assert len(fired) == 1 and fired[0].kind == AlertKind.BANTUAN and fired[0].internal is True
    assert "Warga Dua" not in fired[0].message and str(HULU[0]) not in fired[0].message  # tanpa nama/lokasi
    notifier.deliver(db.get_bind(), [a.id for a in fired])
    db.expire_all()
    assert {d.recipient for d in db.scalars(select(AlertDelivery).where(AlertDelivery.alert_id == fired[0].id))} == {"2001", "6001"}  # koordinator + Tim SAR saja
    assert disaster.unconfirmed_tick(db, now + timedelta(minutes=settings.unconfirmed_minutes + 2)) == []  # idempoten
    assert len(_duga(db, now)) == 1
    mine = client.get("/me/resident", headers=login("warga1")).json()
    assert mine["latest_status"] == "aman_mandiri"  # yang menjawab tidak ditandai
    queue = client.get("/help-requests", headers=login("koord_rw01")).json()
    assert [(q["resident"]["name"], q["source"]) for q in queue] == [("Warga Dua", "sistem")]


def test_continued_overflow_updates_do_not_restart_the_wait(client, login, ids, db):
    _share(client, login, "warga2", HULU)
    _river(client, login, ids)
    db.expire_all()
    first = db.scalars(select(RiverStatusLog)).first()
    first.created_at = utcnow() - timedelta(minutes=settings.unconfirmed_minutes + 5)
    db.commit()
    _river(client, login, ids)  # pembaruan Meluap berulang: awal bencana tetap yang pertama
    disaster.unconfirmed_tick(db, utcnow())
    db.commit()
    assert len(_duga(db, utcnow())) == 1


def test_no_consent_or_no_disaster_means_no_suspicion(client, login, ids, db):
    _share(client, login, "warga2", HULU)
    assert disaster.unconfirmed_tick(db, utcnow() + timedelta(hours=1)) == []  # tidak ada bencana
    _river(client, login, ids)
    client.delete("/me/location-consent", headers=login("warga2"))  # izin dicabut: lokasi dihapus
    assert disaster.unconfirmed_tick(db, utcnow() + timedelta(minutes=settings.unconfirmed_minutes + 1)) == []
    assert _duga(db, utcnow()) == []


# ---------- peta Tim SAR ----------
def test_sar_map_lists_people_needing_help_only_during_disaster(client, login, ids, db):
    _share(client, login, "warga2", HULU)
    client.post("/me/status", json={"status": "butuh_bantuan", "need_type": "medis"}, headers=login("warga2"))
    h = login("sar1")
    before = client.get("/sar/needs", headers=h).json()
    assert before["disaster_active"] is False and before["items"] == []  # lokasi tidak dibuka di luar bencana
    _river(client, login, ids)
    out = client.get("/sar/needs", headers=h).json()
    assert out["disaster_active"] is True and "bukan keputusan" in out["note"]
    names = {i["name"]: i for i in out["items"]}
    assert set(names) == {"Warga Dua"}  # hanya yang butuh/diduga butuh bantuan
    item = names["Warga Dua"]
    assert item["status"] == "butuh_bantuan" and item["lat"] == HULU[0] and item["location_source"] == "terkini"
    assert item["priority"] in ("kritis", "tinggi", "sedang") and item["factors"]
    disaster.unconfirmed_tick(db, utcnow() + timedelta(minutes=settings.unconfirmed_minutes + 1))
    db.commit()
    _share(client, login, "warga1", HULU)  # warga1 diam di zona -> diduga
    disaster.unconfirmed_tick(db, utcnow() + timedelta(minutes=settings.unconfirmed_minutes + 2))
    db.commit()
    statuses = {i["name"]: i["status"] for i in client.get("/sar/needs", headers=h).json()["items"]}
    assert statuses == {"Warga Dua": "butuh_bantuan", "Warga Satu": "duga_butuh_bantuan"}
    db.expire_all()
    assert "sar.needs.view" in set(db.scalars(select(AuditLog.action)))  # akses lokasi tercatat


def test_evacuated_residents_leave_the_sar_map(client, login, ids, db):
    _share(client, login, "warga2", HULU)
    client.post("/me/status", json={"status": "butuh_bantuan", "need_type": "evakuasi"}, headers=login("warga2"))
    _river(client, login, ids)
    assert len(client.get("/sar/needs", headers=login("sar1")).json()["items"]) == 1
    h = login("koord_rw01")
    r = client.post(f"/residents/{ids['Warga Dua']}/status", json={"status": "tiba_di_titik_aman", "note": "Di shelter"},
                    headers=h)
    assert r.status_code == 201
    assert client.get("/sar/needs", headers=login("sar1")).json()["items"] == []


# ---------- retensi (FR-056) ----------
def test_old_locations_are_purged_unless_disaster_is_active(client, login, ids, db):
    _share(client, login, "warga1", HULU)
    _share(client, login, "warga2", HILIR)
    db.expire_all()
    from app.models import Resident
    for r in db.scalars(select(Resident).where(Resident.last_lat.is_not(None))):
        r.last_location_at = utcnow() - timedelta(hours=settings.location_retention_hours + 5)
    db.commit()
    _river(client, login, ids)  # Mode Bencana aktif di kelurahan: lokasi dipertahankan
    assert disaster.purge_locations(db, utcnow()) == 0
    _river(client, login, ids, "normal")
    assert disaster.purge_locations(db, utcnow()) == 2
    db.commit()
    assert client.get("/me/resident", headers=login("warga1")).json()["last_lat"] is None


def test_resident_picks_nearest_station_and_sees_live_status(client, login, ids):
    h = login("warga1")
    sid = ids["Pos Pantau Hulu"]  # waspada 150, bahaya 250
    assert client.post("/me/location-consent", json={"station_id": 9999}, headers=h).status_code == 422
    c = client.post("/me/location-consent", json={"station_id": sid}, headers=h).json()
    assert c["granted"] is True and c["near_station"]["name"] == "Pos Pantau Hulu"
    client.post(f"/stations/{sid}/observations", json={"level_cm": 270}, headers=login("pospantau1"))
    ns = client.get("/me/location-consent", headers=h).json()["near_station"]
    assert ns["status"] == "meluap" and ns["level_cm"] == 270  # dari angka live, tanpa tombol kondisi
    client.post(f"/stations/{sid}/observations", json={"level_cm": 90}, headers=login("pospantau1"))
    assert client.get("/me/location-consent", headers=h).json()["near_station"]["status"] == "normal"
