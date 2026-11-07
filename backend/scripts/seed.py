"""Buat database MySQL (jika belum ada), tabel, wilayah demo, akun demo, pos pantau, warga, dan shelter nyata Bandung.

Jalankan dari folder backend/:  python -m scripts.seed
Aman diulang: data yang sudah ada tidak diduplikasi.
    python -m scripts.seed --reset          HAPUS semua tabel lalu buat ulang (WAJIB setelah skema berubah)
    python -m scripts.seed --demo-verify    tandai shelter dalam radius 6 km dari lokasi demo sebagai TERVERIFIKASI,
                                            hanya agar navigasi bisa dicoba. Di lapangan, koordinator yang memverifikasi.
"""
import json
import sys
from pathlib import Path

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.config import settings
from app.db import Base, SessionLocal, engine, utcnow
from app.models import (
    EvacuationRoute,
    FamilyMember,
    Region,
    RegionLevel,
    Resident,
    Role,
    RouteStatus,
    Shelter,
    ShelterStatus,
    Station,
    User,
    Vulnerability,
)
from app.services.geo import haversine_m

DATA = Path(__file__).resolve().parent.parent / "data" / "shelters_bandung_osm.json"
DEMO_CENTER = (-6.8830, 107.6110)
DEMO_VERIFY_RADIUS_M = 6000

# Hierarki administratif demo; pilot asli menunggu keputusan D-01/D-02 di PRD.
REGIONS = [
    ("Jawa Barat", RegionLevel.PROVINSI, None),
    ("Kota Bandung", RegionLevel.KABUPATEN_KOTA, "Jawa Barat"),
    ("Kecamatan Demo", RegionLevel.KECAMATAN, "Kota Bandung"),
    ("Kelurahan Demo", RegionLevel.KELURAHAN, "Kecamatan Demo"),
    ("RW 01", RegionLevel.RW, "Kelurahan Demo"),
    ("RW 02", RegionLevel.RW, "Kelurahan Demo"),
    ("RT 01 / RW 01", RegionLevel.RT, "RW 01"),
    ("RT 02 / RW 01", RegionLevel.RT, "RW 01"),
    ("RT 01 / RW 02", RegionLevel.RT, "RW 02"),
    ("RT 02 / RW 02", RegionLevel.RT, "RW 02"),
]

# 5 role (PRD v2 §5): warga, koordinator, pos_pantau, tim_sar, admin
USERS = [
    ("admin", "Admin Sistem", Role.ADMIN, "Kelurahan Demo"),
    ("koord_rw01", "Koordinator RW 01", Role.KOORDINATOR, "RW 01"),
    ("koord_rw02", "Koordinator RW 02", Role.KOORDINATOR, "RW 02"),
    ("pospantau1", "Petugas Pos Pantau Hulu", Role.POS_PANTAU, "RW 01"),
    ("pospantau2", "Petugas Pos Pantau Hilir", Role.POS_PANTAU, "RW 02"),
    ("relawan1", "Relawan Satu", Role.TIM_SAR, "RW 01"),
    ("relawan2", "Relawan Dua", Role.TIM_SAR, "RW 02"),
    ("timsar1", "Tim SAR Satu", Role.TIM_SAR, "Kelurahan Demo"),
    ("timsar2", "Tim SAR Dua", Role.TIM_SAR, "Kelurahan Demo"),
    ("warga1", "Warga Satu", Role.WARGA, "RT 01 / RW 01"),
    ("warga2", "Warga Dua", Role.WARGA, "RT 02 / RW 01"),
    ("warga3", "Warga Tiga", Role.WARGA, "RT 01 / RW 02"),
]

# Pos pemantauan nyata banjir / AWLR di berbagai aliran sungai Kota Bandung
# (nama, wilayah, lat, lng, hulu?, sungai, ambang waspada cm, ambang bahaya cm)
STATIONS = [
    ("Pos Pantau Hulu", "RT 01 / RW 01", -6.8845, 107.6115, True, "Sungai Cikapundung (Gandok Dago)", 150, 250),
    ("Pos Pantau Hilir", "RT 01 / RW 02", -6.9142, 107.6098, False, "Sungai Cikapundung (Viaduct)", 140, 220),
    ("Pos Pantau Citepus Pagarsih", "RT 02 / RW 01", -6.9238, 107.5954, False, "Sungai Citepus (Pagarsih)", 120, 180),
    ("Pos Pantau Cidurian Rancacili", "RT 02 / RW 02", -6.9580, 107.6650, False, "Sungai Cidurian (Rancacili)", 130, 200),
    ("Pos Pantau Cibeureum Rajawali", "RW 01", -6.9050, 107.5680, False, "Sungai Cibeureum (Rajawali)", 140, 210),
    ("Pos Pantau Cinambo Gedebage", "RW 02", -6.9460, 107.6910, False, "Sungai Cinambo (Gedebage)", 110, 170),
]

# (nama, wilayah, username akun atau None, punya smartphone, kerentanan, catatan bantuan, lokasi rumah)
RESIDENTS = [
    ("Warga Satu", "RT 01 / RW 01", "warga1", True, [], None, (-6.8808, 107.6104)),
    ("Warga Dua", "RT 02 / RW 01", "warga2", True, [], None, (-6.8840, 107.6112)),
    ("Warga Tiga", "RT 01 / RW 02", "warga3", True, [], None, (-6.9005, 107.6160)),
    ("Mbah Sutini", "RT 01 / RW 01", None, False, [Vulnerability.LANSIA, Vulnerability.DISABILITAS],
     "Menggunakan kursi roda, perlu dua pendamping saat evakuasi", (-6.8812, 107.6098)),
    ("Pak Darto", "RT 02 / RW 01", None, False, [Vulnerability.TINGGAL_SENDIRI], None, (-6.8835, 107.6125)),
    ("Bu Rina", "RT 02 / RW 02", None, True, [Vulnerability.HAMIL], None, (-6.8990, 107.6175)),
]

# Data keluarga (FR-060): (nama kepala keluarga, nama anggota, hubungan, usia, kerentanan, catatan)
FAMILY = [
    ("Mbah Sutini", "Raka", "cucu", 3, [], "Perlu digendong; alergi susu"),
    ("Mbah Sutini", "Sulastri", "anak", 41, [], None),
    ("Bu Rina", "Aisyah", "anak", 4, [], None),
    ("Bu Rina", "Nenek Aminah", "ibu", 67, [Vulnerability.SAKIT], "Penyakit jantung, bawa obat"),
]

# Shelter default untuk tes & demo (selain shelter nyata OSM Bandung)
SHELTERS = [
    ("Masjid Al-Ikhlas", "RT 01 / RW 01", -6.8850, 107.6080, "Jl. Lembah 12", 150, True),
    ("Balai RW 02", "RW 02", -6.9010, 107.6160, "Jl. Dataran 5", 80, True),
]

ROUTES = [
    ("Jalur RT 01 ke Masjid Al-Ikhlas", "RW 01", "Masjid Al-Ikhlas",
     [(-6.8808, 107.6104), (-6.8818, 107.6100), (-6.8832, 107.6092), (-6.8845, 107.6084), (-6.8850, 107.6080)]),
]


def load_shelters() -> list[dict]:
    if not DATA.exists():
        return []
    return json.loads(DATA.read_text(encoding="utf-8")).get("shelters", [])


def ensure_database() -> None:
    url = make_url(settings.database_url)
    if not url.drivername.startswith("mysql"):
        return
    server = create_engine(url.set(database=""))
    with server.connect() as conn:
        conn.execute(text(
            f"CREATE DATABASE IF NOT EXISTS `{url.database}` "
            "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
        ))
        conn.commit()
    server.dispose()


def seed_data(db: Session, password: str, demo_verify: bool = False) -> dict[str, Region]:
    """Isi wilayah + akun + pos + warga + keluarga + shelter nyata ke sesi (idempoten). Dipakai juga oleh tes."""
    by_name: dict[str, Region] = {r.name: r for r in db.scalars(select(Region))}
    for name, level, parent in REGIONS:
        if name not in by_name:
            r = Region(name=name, level=level, parent_id=by_name[parent].id if parent else None)
            db.add(r)
            db.flush()
            by_name[name] = r

    existing = set(db.scalars(select(User.username)))
    pw = hash_password(password)
    for username, name, role, region in USERS:
        if username not in existing:
            db.add(User(username=username, name=name, role=role,
                        region_id=by_name[region].id, password_hash=pw))
    db.flush()
    user_ids = {u.username: u.id for u in db.scalars(select(User))}

    existing = set(db.scalars(select(Station.name)))
    for name, region, lat, lng, upstream, river, warn, danger in STATIONS:
        if name not in existing:
            db.add(Station(name=name, region_id=by_name[region].id, lat=lat, lng=lng, is_upstream=upstream,
                           river_name=river, warning_cm=warn, danger_cm=danger, condition="normal"))

    existing = set(db.scalars(select(Resident.name)))
    for name, region, username, phone_ok, vuln, notes, home in RESIDENTS:
        if name not in existing:
            db.add(Resident(name=name, region_id=by_name[region].id,
                            user_id=user_ids[username] if username else None, has_smartphone=phone_ok,
                            vulnerability=[v.value for v in vuln], assistance_notes=notes,
                            consent=bool(vuln or notes), home_lat=home[0], home_lng=home[1]))
    db.flush()

    residents = {r.name: r for r in db.scalars(select(Resident))}
    have = {(m.resident_id, m.name) for m in db.scalars(select(FamilyMember))}
    for head, name, relation, age, vuln, note in FAMILY:
        r = residents.get(head)
        if r is not None and (r.id, name) not in have:
            if (vuln or note) and not r.consent:
                r.consent = True  # data keluarga sensitif butuh persetujuan (demo)
            db.add(FamilyMember(resident_id=r.id, name=name, relation=relation, age=age,
                                vulnerability=[v.value for v in vuln], note=note,
                                created_by=user_ids["koord_rw01"], created_at=utcnow()))

    existing_shelters = set(db.scalars(select(Shelter.name)))
    for name, region, lat, lng, address, capacity, verified in SHELTERS:
        if name not in existing_shelters:
            db.add(Shelter(name=name, region_id=by_name[region].id, lat=lat, lng=lng, address=address,
                           capacity=capacity, status=ShelterStatus.TERSEDIA, is_verified=verified,
                           verified_by=user_ids["admin"] if verified else None,
                           verified_at=utcnow() if verified else None))
    db.flush()

    shelter_ids = {s.name: s.id for s in db.scalars(select(Shelter))}
    existing_routes = set(db.scalars(select(EvacuationRoute.name)))
    for name, region, shelter, points in ROUTES:
        if name not in existing_routes and shelter in shelter_ids:
            db.add(EvacuationRoute(name=name, region_id=by_name[region].id, shelter_id=shelter_ids[shelter],
                                   points=[list(p) for p in points], status=RouteStatus.TERVERIFIKASI,
                                   note="Contoh rute resmi; validasi lapangan sebelum dipakai",
                                   verified_by=user_ids["admin"], verified_at=utcnow(),
                                   created_by=user_ids["admin"]))
    db.flush()

    # Shelter nyata Kota Bandung (OpenStreetMap). Selalu BELUM terverifikasi kecuali --demo-verify.
    city_id = by_name["Kota Bandung"].id
    known = set(db.scalars(select(Shelter.osm_ref).where(Shelter.osm_ref.is_not(None))))
    now = utcnow()
    for s in load_shelters():
        if s["osm_ref"] in known:
            continue
        near = haversine_m(DEMO_CENTER[0], DEMO_CENTER[1], s["lat"], s["lng"]) <= DEMO_VERIFY_RADIUS_M
        verified = demo_verify and near
        db.add(Shelter(
            name=s["name"][:120], region_id=city_id, lat=s["lat"], lng=s["lng"], address=s["address"][:255],
            capacity=s.get("capacity"), contact=(s.get("contact") or None), status=ShelterStatus.TERSEDIA,
            is_verified=verified, verified_by=user_ids["koord_rw01"] if verified else None,
            verified_at=now if verified else None, kind=s.get("kind"), osm_ref=s["osm_ref"],
            source=f"OpenStreetMap {s['osm_ref']} (ODbL)" + (" — verifikasi DEMO" if verified else " — belum diverifikasi"),
        ))
    db.commit()
    return by_name


def seed() -> None:
    if not settings.seed_password:
        sys.exit("SEED_PASSWORD kosong di .env")

    ensure_database()
    if "--reset" in sys.argv:
        with engine.begin() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
            Base.metadata.drop_all(conn)
            conn.execute(text("DROP TABLE IF EXISTS families;"))
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
        print("Semua tabel dihapus (--reset).")
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_data(db, settings.seed_password, demo_verify="--demo-verify" in sys.argv)
        total = db.scalar(select(func.count(Shelter.id)))
        ok = db.scalar(select(func.count(Shelter.id)).where(Shelter.is_verified.is_(True)))
    print(f"Seed selesai: {len(REGIONS)} wilayah, {len(USERS)} akun, {len(STATIONS)} pos pantau, "
          f"{len(RESIDENTS)} warga, {total} shelter nyata (OSM), {ok} terverifikasi.")
    if not ok:
        print("Belum ada shelter terverifikasi: login koordinator lalu verifikasi di tab Shelter, "
              "atau jalankan ulang dengan --demo-verify (khusus demo).")


if __name__ == "__main__":
    seed()
