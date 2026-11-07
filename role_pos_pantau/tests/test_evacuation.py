"""Lokasi warga & prioritas evakuasi."""
from sqlalchemy import select

from app.models import Alert, AuditLog
from conftest import HULU


def _prio(client, login, user="koord_rw01", **params):
    r = client.get("/evacuation/priorities", params=params, headers=login(user))
    assert r.status_code == 200, r.text
    return r.json()


def test_priority_ranks_vulnerable_and_requesting_first(client, login, report, ids):
    iid = report("warga1")["incident_id"]
    client.post(f"/incidents/{iid}/level", json={"level": "siaga", "reason": "Cek lapangan"}, headers=login("pospantau1"))
    client.post("/me/location-consent", headers=login("warga2"))  # izin lokasi sekali
    # lokasi terkini hanya terlihat saat Mode Bencana: pos hulu menetapkan sungai Meluap
    client.post(f"/stations/{ids['Pos Pantau Hulu']}/condition", json={"status": "meluap"}, headers=login("pospantau1"))
    client.post("/me/status", json={"status": "butuh_bantuan", "need_type": "medis", "lat": HULU[0], "lng": HULU[1]},
                headers=login("warga2"))
    d = _prio(client, login)
    assert d["incident"]["id"] == iid
    names = [x["name"] for x in d["items"]]
    assert names[:2] == ["Mbah Sutini", "Warga Dua"] or names[:2] == ["Warga Dua", "Mbah Sutini"]
    top = {x["name"]: x for x in d["items"]}
    assert top["Warga Dua"]["location_source"] == "terkini"
    assert top["Mbah Sutini"]["location_source"] == "rumah"
    assert top["Mbah Sutini"]["priority"] in ("kritis", "tinggi")
    assert {f["faktor"] for f in top["Mbah Sutini"]["factors"]} >= {"status", "kerentanan", "tanpa_smartphone"}
    assert top["Mbah Sutini"]["nearest_shelter"]["name"] == "Sasana Budaya Ganesha (Sabuga ITB)"
    assert "Bu Rina" not in names  # RW 02 di luar wilayah koord_rw01


def test_safe_residents_excluded_and_unknown_location_flagged(client, login, ids):
    h = login("koord_rw01")
    client.post(f"/residents/{ids['Pak Darto']}/status", json={"status": "aman_terverifikasi", "note": "Ditemui RT"},
                headers=h)
    client.post("/residents", json={"name": "Pak Tanpa Lokasi", "region_id": ids["RT 01 / RW 01"]}, headers=h)
    items = {x["name"]: x for x in _prio(client, login)["items"]}
    assert "Pak Darto" not in items
    assert items["Pak Tanpa Lokasi"]["lat"] is None
    assert "lokasi_tidak_diketahui" in {f["faktor"] for f in items["Pak Tanpa Lokasi"]["factors"]}


def test_priorities_restricted_and_audited(client, login, db):
    for u in ("warga1", "sar1", "pospantau1"):
        assert client.get("/evacuation/priorities", headers=login(u)).status_code == 403
    _prio(client, login)
    assert "evacuation.view" in set(db.scalars(select(AuditLog.action)))


def test_share_location_and_home(client, login, ids):
    h = login("warga1")
    assert client.post("/me/location", json={"lat": -6.881, "lng": 107.611}, headers=h).status_code == 403  # belum izin
    assert client.post("/me/location-consent", headers=h).status_code == 201
    r = client.post("/me/location", json={"lat": -6.881, "lng": 107.611}, headers=h)
    assert r.status_code == 200 and r.json()["last_lat"] == -6.881
    r = client.post("/me/location", json={"lat": -6.882, "lng": 107.612, "kind": "rumah"}, headers=h)
    assert r.json()["home_lat"] == -6.882
    assert client.post("/me/location", json={"lat": 99, "lng": 0}, headers=h).status_code == 422
    assert client.post("/me/status", json={"status": "aman", "lat": -6.88}, headers=h).status_code == 422


def test_locations_never_in_alert_messages(client, login, report, db):
    client.post("/me/location", json={"lat": -6.88123, "lng": 107.61234}, headers=login("warga1"))
    iid = report("warga1")["incident_id"]
    client.post(f"/incidents/{iid}/level", json={"level": "waspada", "reason": "Cek lapangan"},
                headers=login("koord_rw01"))
    for a in db.scalars(select(Alert)):
        assert "6.88123" not in a.message and "107.61234" not in a.message
