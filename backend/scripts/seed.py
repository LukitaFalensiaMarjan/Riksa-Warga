"""Buat database MySQL (jika belum ada), tabel, wilayah demo, dan akun demo.

Jalankan dari folder backend/:  python -m scripts.seed
Aman diulang: data yang sudah ada tidak diduplikasi.
    python -m scripts.seed --reset   HAPUS semua tabel lalu buat ulang (perlu setelah skema berubah)
"""
import sys

from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.config import settings
from app.db import Base, SessionLocal, engine, utcnow
from app.models import (
    EvacuationRoute,
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

# Data wilayah dummy untuk demo; pilot asli menunggu keputusan D-01/D-02 di PRD.
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

USERS = [
    ("admin", "Admin Sistem", Role.ADMIN, "Kelurahan Demo"),
    ("koord_rw01", "Koordinator RW 01", Role.KOORDINATOR, "RW 01"),
    ("koord_rw02", "Koordinator RW 02", Role.KOORDINATOR, "RW 02"),
    ("pospantau1", "Petugas Pos Pantau Hulu", Role.POS_PANTAU, "RW 01"),
    ("pospantau2", "Petugas Pos Pantau Hilir", Role.POS_PANTAU, "RW 02"),
    ("relawan1", "Relawan Satu", Role.RELAWAN, "RW 01"),
    ("relawan2", "Relawan Dua", Role.RELAWAN, "RW 02"),
    ("warga1", "Warga Satu", Role.WARGA, "RT 01 / RW 01"),
    ("warga2", "Warga Dua", Role.WARGA, "RT 02 / RW 01"),
    ("warga3", "Warga Tiga", Role.WARGA, "RT 01 / RW 02"),
]

# Koordinat dummy di sekitar Bandung; ambang tinggi air adalah asumsi demo, bukan data lapangan.
# (nama, wilayah, lat, lng, hulu?, sungai, ambang waspada cm, ambang bahaya cm)
STATIONS = [
    ("Pos Pantau Hulu", "RT 01 / RW 01", -6.8800, 107.6100, True, "Sungai Demo", 150, 250),
    ("Pos Pantau Hilir", "RT 01 / RW 02", -6.9000, 107.6150, False, "Sungai Demo", 120, 200),
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

# Rute evakuasi resmi contoh: RT 01/RW 01 -> Masjid Al-Ikhlas (titik dummy, perlu validasi lapangan)
ROUTES = [
    ("Jalur RT 01 ke Masjid Al-Ikhlas", "RW 01", "Masjid Al-Ikhlas",
     [(-6.8808, 107.6104), (-6.8818, 107.6100), (-6.8832, 107.6092), (-6.8845, 107.6084), (-6.8850, 107.6080)]),
]

# (nama, wilayah, lat, lng, alamat, kapasitas, terverifikasi)
SHELTERS = [
    ("Masjid Al-Ikhlas", "RW 01", -6.8850, 107.6080, "Jl. Demo No. 1", 150, True),
    ("Balai RW 02", "RW 02", -6.8950, 107.6200, "Jl. Demo No. 20", 80, True),
    ("Lapangan Demo", "RW 02", -6.8970, 107.6180, "Jl. Demo No. 25", None, False),
]


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


def seed_data(db: Session, password: str) -> dict[str, Region]:
    """Isi wilayah + akun demo ke sesi (idempoten). Dipakai juga oleh tes."""
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
                           river_name=river, warning_cm=warn, danger_cm=danger))

    existing = set(db.scalars(select(Resident.name)))
    for name, region, username, phone_ok, vuln, notes, home in RESIDENTS:
        if name not in existing:
            db.add(Resident(name=name, region_id=by_name[region].id,
                            user_id=user_ids[username] if username else None, has_smartphone=phone_ok,
                            vulnerability=[v.value for v in vuln], assistance_notes=notes,
                            consent=bool(vuln or notes), home_lat=home[0], home_lng=home[1]))

    existing = set(db.scalars(select(Shelter.name)))
    for name, region, lat, lng, address, capacity, verified in SHELTERS:
        if name not in existing:
            db.add(Shelter(name=name, region_id=by_name[region].id, lat=lat, lng=lng, address=address,
                           capacity=capacity, status=ShelterStatus.TERSEDIA, is_verified=verified,
                           verified_by=user_ids["admin"] if verified else None,
                           verified_at=utcnow() if verified else None))
    db.flush()

    shelter_ids = {s.name: s.id for s in db.scalars(select(Shelter))}
    existing = set(db.scalars(select(EvacuationRoute.name)))
    for name, region, shelter, points in ROUTES:
        if name not in existing:
            db.add(EvacuationRoute(name=name, region_id=by_name[region].id, shelter_id=shelter_ids[shelter],
                                   points=[list(p) for p in points], status=RouteStatus.TERVERIFIKASI,
                                   note="Contoh demo; validasi lapangan sebelum dipakai",
                                   verified_by=user_ids["admin"], verified_at=utcnow(),
                                   created_by=user_ids["admin"]))
    db.commit()
    return by_name


def seed() -> None:
    if not settings.seed_password:
        sys.exit("SEED_PASSWORD kosong di .env")

    ensure_database()
    if "--reset" in sys.argv:
        Base.metadata.drop_all(engine)  # data demo hilang semua
        print("Semua tabel dihapus (--reset).")
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed_data(db, settings.seed_password)
    print(f"Seed selesai: {len(REGIONS)} wilayah, {len(USERS)} akun, {len(STATIONS)} pos pantau, "
          f"{len(RESIDENTS)} warga, {len(SHELTERS)} shelter.")


if __name__ == "__main__":
    seed()
