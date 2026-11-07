# Role WARGA — fitur, mekanisme, dan peta file

Folder ini berisi aplikasi lengkap (bisa langsung di-run, lihat `README_INTEGRASI.md` di root zip). Dokumen ini
menandai bagian yang menjadi milik role **Warga** supaya tidak ada yang tertinggal saat integrasi.

Login demo: `warga1` (RT 01/RW 01), `warga2`, `warga3` (RW 02). Menu warga: Beranda · Live Monitoring ·
Lapor Kejadian · Peta Evakuasi & Shelter · Laporan Saya · Peringatan.

## 1. Fitur & mekanisme

| Fitur | Mekanisme singkat |
|---|---|
| **Beranda** | Kartu kondisi wilayah. Merah/oranye bila ada peringatan kejadian aktif **atau** bila pos pantau terdekat pilihan warga berstatus Waspada/Meluap menurut **angka tinggi air live** (tanpa menunggu tombol kondisi pos). |
| **Status keselamatan** | Tombol *Saya Aman* / *Butuh Bantuan* (evakuasi/medis/logistik + catatan + lokasi opsional) → `POST /me/status`. Butuh Bantuan masuk antrean koordinator & Tim SAR. |
| **Izin lokasi sekali + verifikasi lokasi** | Warga memilih **pos pantau (sungai) terdekat** dari tempatnya (dropdown, atau "Pilih otomatis dari GPS"), lalu memberi izin berbagi lokasi **sekali** (berlaku sampai dicabut). Cabut izin = lokasi terkini dihapus. |
| **Mode Bencana** | Aktif otomatis bila ada pos Meluap / pengumuman meluap. Saat aktif & aplikasi terbuka, lokasi terkini dikirim. Warga di zona bahaya yang tidak memberi kabar dalam `UNCONFIRMED_MINUTES` → status **Diduga Butuh Bantuan** (terlihat Tim SAR). |
| **Live Monitoring** | 7 pos pantau, data tinggi muka air diperbarui tiap 3 detik (simulator), status Normal/Waspada/Meluap, tren, popup detail + grafik 12 jam, koordinat, ambang, Google Maps, navigasi ke shelter. Cuaca langsung Open-Meteo. |
| **Prediksi risiko** | Kartu "Potensi banjir" (rendah/sedang/tinggi) dari prakiraan BMKG + kondisi sungai + laju naik. Perkiraan, bukan kepastian. |
| **Lapor Kejadian** | Judul, **kondisi air** (Normal, Air naik, Arus deras, Genangan, Meluap, Air masuk rumah, Surut), deskripsi, **area pos pantau** (otomatis terisi pos terdekat dari Beranda), pin peta/GPS, foto (JPG/PNG/WebP ≤5 MB), label simulasi. Offline → disimpan di perangkat dan dikirim otomatis saat online (antrean, tanpa duplikat). |
| **Laporan Saya** | Urutan 1..n laporan milik warga + ID sistem, kondisi air, status (diterima/terverifikasi/ditolak/duplikat dari ID #x), area, catatan pos pantau, kejadian, foto. |
| **Peta Evakuasi & Shelter** | Satu halaman: peta shelter, titik bahaya, rute resmi; cari rute jalan kaki terdekat (OSRM) dengan peringatan bahaya di rute; navigasi live (kompas + jarak); daftar shelter urut terdekat; mode offline (rute tersimpan / arah kompas). |
| **Peringatan** | Semua alert untuk wilayah warga (kejadian, kondisi sungai, buletin pos pantau, prediksi, shelter penuh, koreksi). Telegram/SMS lewat `app/services/notifier.py`. |
| **Profil / Telegram** | Isi chat ID Telegram & nomor HP sendiri (`PATCH /auth/me`). |

## 2. Endpoint API yang dipakai role Warga

| Method | Path | Akses |
|---|---|---|
| POST | `/auth/login` | publik |
| GET, PATCH | `/auth/me` | login |
| GET | `/me/resident` | warga |
| POST | `/me/status` | warga |
| POST | `/me/location` | warga |
| GET, POST, DELETE | `/me/location-consent` | warga (POST menerima `{"station_id": <pos terdekat>}`) |
| POST | `/reports` | warga, pos pantau |
| GET | `/reports/mine` | login |
| GET | `/reports/{id}` | pelapor sendiri / pos pantau |
| POST, GET | `/reports/{id}/photo` | login (pemilik laporan) |
| GET | `/nature`, `/nature/live`, `/nature/stations/{id}` | warga, pos pantau, koordinator, SAR |
| GET | `/stations`, `/stations/{id}/trend` | login |
| GET | `/alerts` | login |
| GET | `/shelters` | login (warga hanya melihat shelter terverifikasi) |
| GET | `/routing/shelter`, `/evacuation-routes`, `/road-conditions` | login |
| GET | `/regions/lookup` | login |
| GET | `/health`, `/config` | publik |

## 3. File milik / dipakai role Warga

**Backend**
- `app/routers/residents.py` — bagian `/me/*` (status, lokasi, izin lokasi + pos terdekat `_near_station`)
- `app/routers/reports.py` — `create_report`, `my_reports`, foto
- `app/routers/nature.py`, `app/routers/stations.py` (GET) — live monitoring
- `app/routers/routes.py` — rute ke shelter (OSRM), kondisi jalan
- `app/routers/shelters.py` (GET), `app/routers/alerts.py` (GET), `app/routers/auth.py`, `app/routers/regions.py`
- `app/services/disaster.py` — izin lokasi, Mode Bencana, Diduga Butuh Bantuan, purge lokasi
- `app/services/residents.py`, `app/services/evacuation.py` (shelter terdekat), `app/services/routing.py`
- `app/services/nature.py`, `app/services/live_sim.py`, `app/services/weather_live.py`, `app/services/monitoring.py`
- `app/services/engine.py` — `process_new_report` (skor & pengelompokan laporan jadi kejadian)
- Model terkait di `app/models.py`: `Resident` (termasuk `near_station_id`, `location_consent_at`), `ResidentStatusLog`,
  `Report` (`title`, `water_condition`, `station_id`), `WaterCondition`
- Skema di `app/schemas.py`: `ReportCreate`, `ReportMineOut`, `NearStationIn`, `SelfStatusIn`, `LocationIn`

**Frontend** (`static/app.js`, satu file untuk semua role)
- `tabsFor("warga")` — daftar menu warga
- `viewHome` + `homeExtras` — beranda, kartu izin lokasi + pilihan pos terdekat, prediksi, kabar terbaru
- `viewReport` — form lapor (area otomatis dari pos terdekat), `viewMine` — Laporan Saya
- `viewMapNav` — Peta Evakuasi & Shelter, `viewLive` + `tmaCard` + `stationModal` — Live Monitoring
- `viewAlerts` — Peringatan
- `postOrQueue`, `flushQueue` — antrean offline; `getPosition` — GPS; `WATER`/`waterBadge` — kategori kondisi air
- `static/sw.js` — cache offline (app shell + tile peta), `static/manifest.json` — PWA

**Tes yang menjaga fitur warga**
`tests/test_warga.py`, `tests/test_lokasi_bencana.py`, `tests/test_evacuation.py`, `tests/test_routing.py`,
`tests/test_live_monitoring.py`, `tests/test_rbac_matrix.py`

## 4. Ketergantungan ke role lain (jangan dihapus saat integrasi)

- Laporan warga diverifikasi/ditolak oleh **pos pantau** (`/reports/{id}/verify|reject`).
- Status warga & lokasi dipakai **koordinator** (antrean bantuan, prioritas evakuasi) dan **Tim SAR** (peta bantuan).
- Shelter dikelola **koordinator** (verifikasi, status penuh). Warga hanya melihat shelter terverifikasi.
- Buletin/pengumuman dan kondisi sungai dari **pos pantau** muncul di Beranda & Peringatan warga.
