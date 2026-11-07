"""Buat database MySQL (jika belum ada), tabel, wilayah demo, dan akun demo.

Jalankan dari folder backend/:  python -m scripts.seed
Aman diulang: data yang sudah ada tidak diduplikasi.
    python -m scripts.seed --reset   HAPUS semua tabel lalu buat ulang (perlu setelah skema berubah)
"""
import sys

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.auth import hash_password
from app.config import settings
from app.db import Base, SessionLocal, engine, utcnow
from app.models import (
    EvacuationRoute,
    IntegrationSource,
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
    ("sar1", "Tim SAR Satu", Role.TIM_SAR, "Kota Bandung"),
    ("sar2", "Tim SAR Dua", Role.TIM_SAR, "Kota Bandung"),
    ("warga1", "Warga Satu", Role.WARGA, "RT 01 / RW 01"),
    ("warga2", "Warga Dua", Role.WARGA, "RT 02 / RW 01"),
    ("warga3", "Warga Tiga", Role.WARGA, "RT 01 / RW 02"),
]

# Koordinat dummy di sekitar Bandung; ambang tinggi air adalah asumsi demo, bukan data lapangan.
# (nama, wilayah, lat, lng, hulu?, sungai, ambang waspada cm, ambang bahaya cm)
STATIONS = [
    ("Pos Pantau Hulu", "RT 01 / RW 01", -6.8800, 107.6100, True, "Sungai Demo", 150, 250),
    ("Pos Pantau Hilir", "RT 01 / RW 02", -6.9000, 107.6150, False, "Sungai Demo", 120, 200),
    # Lokasi sungai nyata Kota Bandung; koordinat perkiraan & ambang = asumsi demo (perlu validasi lapangan/BPBD).
    ("Pos Pantau Cikapundung Gandok", "Kelurahan Demo", -6.8746, 107.6164, True, "Sungai Cikapundung", 150, 250),
    ("Pos Pantau Cikapundung Viaduct", "Kelurahan Demo", -6.9145, 107.6115, False, "Sungai Cikapundung", 140, 220),
    ("Pos Pantau Citepus Pagarsih", "Kelurahan Demo", -6.9246, 107.5938, False, "Sungai Citepus", 120, 180),
    ("Pos Pantau Cidurian Cicaheum", "Kelurahan Demo", -6.9050, 107.6550, False, "Sungai Cidurian", 130, 200),
    ("Pos Pantau Retensi Gedebage", "Kelurahan Demo", -6.9512, 107.6972, False, "Sungai Cinambo", 150, 230),
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
    ("Jalur RT 01 ke Sabuga ITB", "RW 01", "Sasana Budaya Ganesha (Sabuga ITB)",
     [(-6.8808, 107.6104), (-6.8822, 107.6098), (-6.8836, 107.6090), (-6.8850, 107.6084), (-6.88624, 107.60827)]),
]

# Shelter banjir Kota Bandung: tempat umum besar di dataran yang lebih tinggi & tidak di bantaran sungai.
# Koordinat dari OpenStreetMap (ODbL); ketinggian dari DEM Copernicus via Open-Meteo (Gedebage, titik terendah pos
# pantau, ±664 m dpl). Kapasitas belum diketahui (None). Status "terverifikasi" di sini hanya untuk demo:
# penetapan resmi sebagai tempat evakuasi wajib dikonfirmasi BPBD Kota Bandung & pengelola gedung (PRD D-04).
# (nama, wilayah, lat, lng, alamat, kapasitas, terverifikasi, catatan)
SHELTERS = [
    ("Sasana Budaya Ganesha (Sabuga ITB)", "RW 01", -6.88624, 107.60827, "Jl. Tamansari, Coblong", None, True,
     "Gedung serbaguna; ±753 m dpl"),
    ("Masjid Salman ITB", "RW 01", -6.89369, 107.61120, "Jl. Ganesa, Coblong", None, True, "Masjid & aula; ±772 m dpl"),
    ("PUSDAI Jawa Barat", "RW 02", -6.90013, 107.62592, "Jl. Diponegoro, Cibeunying Kaler", None, True,
     "Pusat dakwah, aula & halaman luas; ±721 m dpl"),
    ("Taman Gasibu", "RW 02", -6.90032, 107.61866, "Jl. Diponegoro (depan Gedung Sate)", None, False,
     "Ruang terbuka/titik kumpul, bukan bangunan; ±732 m dpl"),
    ("Universitas Pendidikan Indonesia (UPI)", "Kelurahan Demo", -6.86113, 107.59180, "Jl. Dr. Setiabudi, Sukasari",
     None, True, "Kampus dataran tinggi utara; ±920 m dpl"),
    ("Taman Budaya Jawa Barat (Dago Tea House)", "Kelurahan Demo", -6.87004, 107.61967,
     "Jl. Bukit Dago Selatan, Coblong", None, True, "Gedung kesenian & halaman; ±859 m dpl"),
    ("GOR Padjajaran", "Kelurahan Demo", -6.90818, 107.60099, "Jl. Pajajaran, Cicendo", None, True,
     "Gelanggang olahraga; ±728 m dpl"),
    ("Stadion Siliwangi", "Kelurahan Demo", -6.91033, 107.61956, "Jl. Lombok, Sumur Bandung", None, True,
     "Stadion & tribun; ±711 m dpl"),
    ("GOR Citra", "Kelurahan Demo", -6.89335, 107.64018, "Kawasan Cikutra, Cibeunying", None, True,
     "Gelanggang olahraga; ±713 m dpl"),
    ("Masjid Raya Bandung", "Kelurahan Demo", -6.92177, 107.60625, "Jl. Alun-Alun Timur, Regol", None, True,
     "Masjid besar pusat kota; ±713 m dpl"),
    ("Stadion Persib (Sidolig)", "Kelurahan Demo", -6.91715, 107.62965, "Jl. Ahmad Yani, Batununggal", None, True,
     "Stadion; ±694 m dpl"),
    ("GOR KONI Bandung", "Kelurahan Demo", -6.91526, 107.63630, "Jl. Jakarta, Kiaracondong", None, True,
     "Gelanggang olahraga; ±689 m dpl"),
    ("SPOrT Jabar Arcamanik", "Kelurahan Demo", -6.91097, 107.67489, "Jl. Pacuan Kuda, Arcamanik", None, True,
     "Kompleks olahraga; untuk wilayah timur (Cicaheum/Gedebage); ±687 m dpl"),
    ("Balai Sartika", "Kelurahan Demo", -6.94225, 107.62549, "Kawasan Buahbatu", None, True,
     "Gedung pertemuan; untuk wilayah selatan; ±686 m dpl"),
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
    for name, region, lat, lng, address, capacity, verified, note in SHELTERS:
        if name not in existing:
            db.add(Shelter(name=name, region_id=by_name[region].id, lat=lat, lng=lng, address=address,
                           capacity=capacity, status=ShelterStatus.TERSEDIA, is_verified=verified,
                           accessibility_note=f"{note}. Koordinat: peta OSM; status resmi perlu konfirmasi BPBD.",
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
    # BMKG prakiraan cuaca (adm4 Sukarasa, Kota Bandung) -> konteks cuaca Kelurahan Demo. Prakiraan, bukan pengamatan.
    if not db.scalar(select(IntegrationSource.id).where(IntegrationSource.kind == "bmkg")):
        db.add(IntegrationSource(name="BMKG Prakiraan Cuaca (Kelurahan Demo)", kind="bmkg",
                                 config={"region_id": by_name["Kelurahan Demo"].id, "adm4": "32.73.01.1001",
                                         "rain_mm": 5.0}, poll_interval_seconds=900))
    db.commit()
    return by_name


def add_missing_columns() -> None:
    """create_all tidak menambah kolom ke tabel lama; tambahkan kolom baru tanpa menghapus data."""
    new = {
        ("reports", "station_id"): "ADD COLUMN station_id INT NULL, "
                                   "ADD CONSTRAINT fk_reports_station FOREIGN KEY (station_id) REFERENCES stations(id)",
        ("reports", "title"): "ADD COLUMN title VARCHAR(120) NULL",
        ("reports", "water_condition"): "ADD COLUMN water_condition VARCHAR(32) NULL",
        ("residents", "near_station_id"): "ADD COLUMN near_station_id INT NULL, ADD CONSTRAINT "
                                          "fk_residents_near_station FOREIGN KEY (near_station_id) REFERENCES stations(id)",
    }
    for (table, name), ddl in new.items():
        if name not in {c["name"] for c in inspect(engine).get_columns(table)}:
            with engine.begin() as conn:
                conn.execute(text(f"ALTER TABLE {table} {ddl}"))
            print(f"Kolom {table}.{name} ditambahkan.")


def seed() -> None:
    if not settings.seed_password:
        sys.exit("SEED_PASSWORD kosong di .env")

    ensure_database()
    if "--reset" in sys.argv:
        Base.metadata.drop_all(engine)  # data demo hilang semua
        print("Semua tabel dihapus (--reset).")
    Base.metadata.create_all(engine)
    add_missing_columns()
    with SessionLocal() as db:
        seed_data(db, settings.seed_password)
    print(f"Seed selesai: {len(REGIONS)} wilayah, {len(USERS)} akun, {len(STATIONS)} pos pantau, "
          f"{len(RESIDENTS)} warga, {len(SHELTERS)} shelter.")


if __name__ == "__main__":
    seed()
