"""Impor kandidat shelter nyata (OSM): hanya kandidat, tidak pernah langsung terverifikasi, idempoten."""
from sqlalchemy import select

from app.models import Shelter
from scripts import import_shelters as imp

ELEMENTS = [
    {"type": "node", "id": 1, "lat": -6.88, "lon": 107.61, "tags": {"emergency": "assembly_point"}},  # tanpa nama
    {"type": "way", "id": 2, "center": {"lat": -6.90, "lon": 107.62}, "tags": {"leisure": "stadium", "name": "GOR Uji Impor",
                                                                              "addr:street": "Jl. Pajajaran"}},
    {"type": "node", "id": 3, "lat": -6.91, "lon": 107.63, "tags": {"amenity": "community_centre", "name": "Balai Uji Impor"}},
    {"type": "node", "id": 4, "lat": -6.91, "lon": 107.63, "tags": {"amenity": "community_centre", "name": "Sudirman Grand Ballroom"}},
    {"type": "node", "id": 5, "lat": -6.92, "lon": 107.60, "tags": {"leisure": "sports_hall", "name": "Ronaldo Futsal Cijerah"}},
    {"type": "node", "id": 6, "lat": -6.92, "lon": 107.60, "tags": {"amenity": "shelter", "name": "Pangkalan Becak Pasar"}},
    {"type": "node", "id": 7, "lat": -6.93, "lon": 107.60, "tags": {"amenity": "community_centre", "name": "Bandung Bee Sanctuary"}},
    {"type": "node", "id": 8, "tags": {"emergency": "assembly_point"}},  # tanpa koordinat
    {"type": "node", "id": 1, "lat": -6.88, "lon": 107.61, "tags": {"emergency": "assembly_point"}},  # ganda
]


def test_candidates_filter_and_label():
    items = {i["ref"]: i for i in imp.candidates(ELEMENTS)}
    assert set(items) == {"OSM node/1", "OSM way/2", "OSM node/3"}  # halte, pangkalan becak, komersial, tanpa koordinat dibuang
    assert items["OSM node/1"]["name"] == "Titik Kumpul (OSM node/1)" and items["OSM node/1"]["kind"] == "titik kumpul"
    assert items["OSM way/2"]["lat"] == -6.90 and items["OSM way/2"]["address"] == "Jl. Pajajaran"
    assert items["OSM node/3"]["address"].startswith("Alamat belum tercatat")


def test_imported_shelters_are_unverified_sourced_and_idempotent(db):
    items = imp.candidates(ELEMENTS)
    assert imp.save(db, "RW 01", items) == (3, 0)
    assert imp.save(db, "RW 01", items) == (0, 3)  # tidak menggandakan
    rows = db.scalars(select(Shelter).where(Shelter.accessibility_note.like("%OpenStreetMap%"))).all()
    assert len(rows) == 3
    for s in rows:
        assert s.is_verified is False and s.verified_by is None and "BELUM diverifikasi" in s.accessibility_note
        assert "Sumber: OSM " in s.accessibility_note


def test_imported_shelters_hidden_from_residents_until_verified(client, login, ids, db):
    imp.save(db, "RW 01", imp.candidates(ELEMENTS))
    names = lambda user: {s["name"] for s in client.get("/shelters", headers=login(user)).json()}  # noqa: E731
    assert "GOR Uji Impor" not in names("warga1")
    assert "GOR Uji Impor" in names("koord_rw01")  # koordinator melihat kandidat untuk diverifikasi
    sid = db.scalar(select(Shelter.id).where(Shelter.name == "GOR Uji Impor"))
    assert client.post(f"/shelters/{sid}/verify", json={"note": "Dicek ke pengelola"}, headers=login("koord_rw01")).status_code == 200
    assert "GOR Uji Impor" in names("warga1")


def test_unknown_region_fails_clearly(db):
    import pytest
    with pytest.raises(SystemExit):
        imp.save(db, "Wilayah Tidak Ada", imp.candidates(ELEMENTS))
