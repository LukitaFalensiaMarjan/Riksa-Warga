"""Rute ke shelter (OSRM di-mock), titik bahaya jalan, rute resmi, laporan offline."""
import httpx
import pytest

from app.services import routing
from conftest import HULU

FROM = (-6.8808, 107.6104)  # rumah Warga Satu


class FakeResp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data


def _osrm(points_sets):
    return {"code": "Ok", "routes": [{
        "distance": 640.0, "duration": 520.0 + i * 60,
        "geometry": {"coordinates": [[lng, lat] for lat, lng in pts]},
        "legs": [{"steps": [{"maneuver": {"type": "depart"}, "name": "Jl. Demo", "distance": 100},
                            {"maneuver": {"type": "turn", "modifier": "left"}, "name": "Gg. Aman", "distance": 300},
                            {"maneuver": {"type": "arrive"}, "name": "", "distance": 0}]}],
    } for i, pts in enumerate(points_sets)]}


@pytest.fixture(autouse=True)
def clear_cache():
    routing._cache.clear()


def test_route_to_nearest_verified_shelter(client, login, monkeypatch):
    calls = []

    def fake_get(url, **kw):
        calls.append(url)
        return FakeResp(_osrm([[FROM, (-6.8830, 107.6095), (-6.8850, 107.6080)]]))

    monkeypatch.setattr(routing.httpx, "get", fake_get)
    d = client.get("/routing/shelter", params={"lat": FROM[0], "lng": FROM[1]}, headers=login("warga1")).json()
    best = d["options"][0]
    assert best["shelter"]["name"] == "Masjid Al-Ikhlas" and best["source"] == "osrm"
    assert "BELUM diverifikasi" in best["label"]
    assert best["steps"][1] == "Belok kiri ke Gg. Aman (300 m)"
    assert "Lapangan Demo" not in {o["shelter"]["name"] for o in d["options"]}  # belum terverifikasi
    assert [r["label"] for r in d["official_routes"]] == ["Rute resmi terverifikasi petugas"]
    assert calls and "107.6104,-6.8808" in calls[0]


def test_hazard_on_route_prefers_alternative(client, login, ids, monkeypatch):
    blocked = [FROM, (-6.8830, 107.6095), (-6.8850, 107.6080)]
    detour = [FROM, (-6.8808, 107.6060), (-6.8850, 107.6060), (-6.8850, 107.6080)]
    monkeypatch.setattr(routing.httpx, "get", lambda url, **kw: FakeResp(_osrm([blocked, detour])))
    r = client.post("/road-conditions", json={"region_id": ids["RW 01"], "kind": "pohon_tumbang",
                                              "lat": -6.8830, "lng": 107.6095, "note": "Pohon besar"},
                    headers=login("relawan1"))
    assert r.status_code == 201
    best = client.get("/routing/shelter", params={"lat": FROM[0], "lng": FROM[1]},
                      headers=login("warga1")).json()["options"][0]
    assert best["hazards"] == [] and best["points"][1] == [-6.8808, 107.6060]  # memilih jalur memutar
    assert best["alternatives_checked"] == 2
    # bila hanya ada jalur terhalang, peringatan wajib tampil
    routing._cache.clear()
    monkeypatch.setattr(routing.httpx, "get", lambda url, **kw: FakeResp(_osrm([blocked])))
    best = client.get("/routing/shelter", params={"lat": FROM[0], "lng": FROM[1]},
                      headers=login("warga1")).json()["options"][0]
    assert any("Pohon tumbang" in w for w in best["warnings"])
    # setelah diselesaikan koordinator, peringatan hilang
    client.post(f"/road-conditions/{r.json()['id']}/resolve", headers=login("koord_rw01"))
    best = client.get("/routing/shelter", params={"lat": FROM[0], "lng": FROM[1]},
                      headers=login("warga1")).json()["options"][0]
    assert best["warnings"] == []


def test_routing_service_down_falls_back_to_straight_line(client, login, monkeypatch):
    def boom(url, **kw):
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(routing.httpx, "get", boom)
    best = client.get("/routing/shelter", params={"lat": FROM[0], "lng": FROM[1]},
                      headers=login("warga1")).json()["options"][0]
    assert best["source"] == "garis_lurus" and len(best["points"]) == 2
    assert "Garis lurus" in best["label"] and best["distance_m"] > 0


def test_active_incident_near_route_warns(client, login, report, monkeypatch):
    monkeypatch.setattr(routing.httpx, "get", lambda url, **kw: FakeResp(_osrm([[FROM, (-6.8850, 107.6080)]])))
    report("warga2", hazard="kebakaran", fire_indicator="api", at=(-6.8830, 107.6092))
    best = client.get("/routing/shelter", params={"lat": FROM[0], "lng": FROM[1]},
                      headers=login("warga1")).json()["options"][0]
    assert any("kebakaran" in w for w in best["warnings"])


def test_evacuation_route_lifecycle(client, login, ids):
    body = {"name": "Jalur Gang Melati", "region_id": ids["RW 01"], "shelter_id": ids["Masjid Al-Ikhlas"],
            "points": [[-6.8812, 107.6098], [-6.8850, 107.6080]]}
    assert client.post("/evacuation-routes", json=body, headers=login("warga1")).status_code == 403
    r = client.post("/evacuation-routes", json=body, headers=login("koord_rw01"))
    assert r.status_code == 201 and r.json()["status"] == "belum_diverifikasi"
    r = client.post(f"/evacuation-routes/{r.json()['id']}/status", json={"status": "terverifikasi", "note": "Dicek"},
                    headers=login("koord_rw01"))
    assert r.json()["verified_by"] == ids["koord_rw01"]
    assert len(client.get("/evacuation-routes", headers=login("warga1")).json()) == 2
    assert client.post("/evacuation-routes", json={**body, "points": [[1, 1]]},
                       headers=login("koord_rw01")).status_code == 422


def test_warga_cannot_report_road_condition(client, login, ids):
    body = {"region_id": ids["RW 01"], "kind": "genangan", "lat": HULU[0], "lng": HULU[1]}
    assert client.post("/road-conditions", json=body, headers=login("warga1")).status_code == 403
    assert client.post("/road-conditions", json={**body, "region_id": ids["Jawa Barat"]},
                       headers=login("relawan1")).status_code == 403  # di luar kelurahan


# PRD §15.1: kirim ulang dari antrean offline tidak membuat duplikat
def test_offline_queue_resend_is_idempotent(client, login, report):
    a = report("warga1", client_ref="off-abc-1")
    b = report("warga1", client_ref="off-abc-1")
    assert a["id"] == b["id"]
    assert len(client.get("/reports/mine", headers=login("warga1")).json()) == 1
    other = report("warga2", client_ref="off-abc-1")  # ref sama dari akun lain = laporan lain
    assert other["id"] != a["id"]
    report("warga1", client_ref="bad ref!", expect=422)


def test_public_config(client):
    c = client.get("/config").json()
    assert "{z}" in c["tile_url"] and isinstance(c["routing_enabled"], bool)
