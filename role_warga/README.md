# Riksa Warga — Backend

API FastAPI + MySQL. Rencana lengkap: [`../docs/PLAN_RIKSA_WARGA.md`](../docs/PLAN_RIKSA_WARGA.md).

## Setup (Windows, dari folder `backend/`)

1. Jalankan MySQL di Laragon (Start All).
2. Buat virtualenv dan pasang dependensi:
   ```bash
   python -m venv .venv
   .venv\Scripts\activate
   pip install -r requirements.txt
   ```
3. Salin `.env.example` ke `.env`, isi `JWT_SECRET` dan sesuaikan `DATABASE_URL`.
4. Buat database, tabel, wilayah demo, dan akun demo:
   ```bash
   python -m scripts.seed
   ```
5. Jalankan API, lalu buka http://127.0.0.1:8000/docs:
   ```bash
   uvicorn app.main:app --reload
   ```

Akun demo: `warga1-3`, `pospantau1-2`, `koord_rw01-02`, `sar1-2`, `admin`, semua memakai `SEED_PASSWORD` dari `.env`.
Seed juga membuat 2 pos pantau (hulu & hilir), 6 data warga (3 tanpa akun, 3 rentan), dan 3 shelter.

Telegram default `TELEGRAM_MODE=mock`: pengiriman hanya dicatat (status `mock`). Nilai di `.env` mengalahkan env var terminal; cek mode aktif di `/health`. Untuk kirim sungguhan isi `TELEGRAM_MODE=live`, `TELEGRAM_BOT_TOKEN`, dan `telegram_chat_id` akun penerima.

## Antarmuka web

Setelah `uvicorn` jalan, buka **http://127.0.0.1:8000/** (Swagger API tetap di `/docs`). Login dengan akun demo; tab yang muncul mengikuti peran:

| Peran | Tab |
|---|---|
| Warga / Relawan | Lapor Kejadian, Laporan Saya, Status Saya, Peringatan, Pos Pantau, Shelter |
| Pos Pantau | Pos Pantau (input tinggi air + grafik), Lapor Kejadian, Laporan Saya, Peringatan |
| Koordinator | Dashboard (peta), Kejadian, Laporan, Warga, Shelter, Pos Pantau, Cuaca & Aturan, Peringatan, Lapor |
| Admin | semua tab koordinator + Admin (akun, aturan, audit log) |

Form lapor memakai **area pos pantau** (bukan RT/RW) sebagai lokasi kejadian, supaya laporan bisa dicocokkan dengan data live pos tersebut. Klik peta/GPS tanpa memilih area = otomatis pos terdekat. Peta memakai Leaflet + OpenStreetMap dari internet.

## Telegram

Isi `.env`: `TELEGRAM_MODE=live`, `TELEGRAM_BOT_TOKEN`, dan `TELEGRAM_DEFAULT_CHAT_ID` (menerima semua alert publik). Alert **internal** (Pantau, usulan Waspada, risiko pos pantau) hanya ke koordinator yang mengisi chat ID lewat tombol **Profil / Telegram** di UI. Setiap akun harus mengirim `/start` ke bot lebih dulu, kalau tidak Telegram menolak (status `GAGAL` + alasan tampil di "Status pengiriman Telegram").

## Tes

Tes memakai SQLite in-memory, tidak butuh MySQL:
```bash
pytest
```

## Endpoint Fase 0

| Method | Path | Akses |
|---|---|---|
| POST | `/auth/login` | publik (maks 5 gagal / 5 menit per username) |
| GET | `/auth/me` | login |
| GET | `/users` | admin (semua), koordinator (wilayahnya) |
| POST | `/users` | admin |
| POST | `/users/{id}/deactivate` | admin, wajib `reason` |
| GET | `/audit-logs` | admin |
| GET | `/regions` | login, dibatasi wilayah |
| GET | `/regions/{id}` | login, dibatasi wilayah |
| POST | `/regions` | admin |

## Endpoint Iterasi 1 (Warga, Koordinator, Pos Pantau)

| Method | Path | Akses |
|---|---|---|
| POST | `/reports` | login (laporan banjir; `from_sensor` hanya pos pantau) |
| GET | `/reports/mine` | login (status laporan sendiri) |
| POST / GET | `/reports/{id}/photo` | pelapor (upload) / pelapor & koordinator (lihat) |
| GET | `/reports`, `/reports/{id}` | koordinator wilayahnya (skor + faktor + tanda pemeriksaan) |
| POST | `/reports/{id}/verify`, `/reports/{id}/reject` | koordinator (tolak wajib `reason`) |
| GET / POST | `/stations` | login (sekelurahan) / koordinator |
| POST | `/stations/{id}/observations` | pos pantau & koordinator wilayahnya |
| GET | `/stations/{id}/trend?hours=6` | login (sekelurahan) |
| GET | `/incidents`, `/incidents/{id}`, `/incidents/{id}/history` | koordinator |
| POST | `/incidents/{id}/level` | koordinator, wajib `reason`; Evakuasi hanya setelah Siaga |
| POST | `/incidents/{id}/verify`, `/proposal/dismiss`, `/cancel`, `/close` | koordinator |
| GET | `/alerts` | warga: alert publik wilayahnya; koordinator: + internal |
| GET | `/alerts/{id}/deliveries` | koordinator |
| GET / POST / PATCH | `/residents`, `/residents/{id}` | koordinator (detail sensitif diaudit) |
| POST / GET | `/residents/{id}/status`, `/residents/{id}/statuses` | koordinator |
| GET | `/residents/summary`, `/help-requests` | koordinator |
| GET / POST | `/me/resident`, `/me/status` | login (Saya Aman / Butuh Bantuan) |
| GET / POST | `/shelters`, `/shelters/{id}/verify`, `/shelters/{id}/status` | warga: terverifikasi saja; koordinator: kelola |
| GET / PUT | `/weather` | login / koordinator |
| GET / PUT | `/rules`, `/rules/{hazard}` | koordinator / admin |
| GET | `/dashboard` | koordinator |

Aturan input:
- `POST /reports` wajib `region_id` = RT/RW **lokasi kejadian** (bukan alamat pelapor); ini menentukan koordinator & audiens alert.
- Semua waktu dari klien wajib berzona, mis. `2026-11-07T14:00:00+07:00`. Tanpa zona ditolak 422.
- Data `source_mode=simulation` selalu jadi kejadian terpisah dan hanya memakai bukti simulasi (cuaca/pos pantau).
- Jalankan API dengan **satu proses** uvicorn: penguncian mesin aturan masih per proses.

Uji alur di `/docs`: login `warga1` dan `warga2`, kirim laporan banjir berdekatan (dekat `-6.8805, 107.6102`), lalu login `koord_rw01` dan buka `/dashboard`.

## Iterasi 3 — Penyempurnaan (BMKG, simulator, matriks RBAC)

> Sebagian digantikan Iterasi 4 (PRD v2): peran Petugas/Instansi dan Relawan dihapus, akun hanya dikelola admin, verifikasi & pengumuman oleh pos pantau.

| Hal | Perilaku |
|---|---|
| **Petugas/Instansi** (`petugas1`, wilayah Kelurahan Demo) | Sesuai PRD §6.2: melihat laporan/kejadian/dashboard, memverifikasi/menolak laporan, mengubah level (Evakuasi tetap hanya setelah Siaga), membatalkan/menutup kejadian, melihat status pengiriman alert, menerima alert internal Telegram. Tidak mengakses data warga rentan, akun, atau konfigurasi. Laporan petugas dihitung sebagai sumber resmi |
| **Akun wilayah (koordinator)** | `POST /users` & `POST /users/{id}/deactivate` kini boleh untuk koordinator, **hanya** peran `warga`/`relawan`/`pos_pantau` di wilayahnya (tidak bisa membuat petugas/koordinator/admin). Akun di luar wilayah tampak tidak ada (404). UI: tab "Akun Wilayah" |
| **BMKG otomatis** | Tabel `integration_sources`; adapter `app/services/integrations.py` menarik `api.bmkg.go.id/publik/prakiraan-cuaca` per kode `adm4` dan mengisi konteks cuaca (hanya faktor pendukung). Berlabel *prakiraan, bukan pengamatan*; berlaku sampai akhir slot 3 jam lalu mati sendiri. Sumber gagal → status `gagal` + galat (galat & config hanya admin), sistem tetap jalan. Konteks cuaca SIMULASI tidak ditimpa. Sinkron otomatis di loop timer (`ENGINE_TICK_SECONDS`), sesuai `poll_interval_seconds` (default 900 dtk). Seed menyertakan 1 sumber (Kelurahan Demo, Sukarasa) |
| **Simulator tinggi air** | `POST /simulation/stations/{id}/step` `{"scenario":"naik"\|"turun"}` (koordinator/admin): menambah pembacaan berlabel `SIMULATION` dan menjalankan mesin aturan seperti data nyata; tidak pernah memengaruhi kejadian nyata. UI: tombol di tab Pos Pantau |
| **Status integrasi** | `GET /integrations` (semua login), `POST/PATCH /integrations` (admin), `POST /integrations/{id}/sync` (admin; koordinator untuk wilayahnya). UI: kartu di tab Cuaca & Aturan |
| **Tes matriks RBAC** | `tests/test_rbac_matrix.py` menguji PRD §6.2 untuk 6 peran terhadap API nyata (403 = ditolak RBAC; 422/404 = lolos RBAC). Menambah peran/endpoint = tambah satu baris |

Tidak ada kolom baru di tabel lama (hanya tabel baru), jadi `python -m scripts.seed` cukup; `--reset` tidak wajib.

Bedanya dengan PRD §6.2 yang masih disengaja: **admin** di proyek ini juga boleh menjalankan aksi operasional (ubah level, tugas) — PRD menyebutnya "konfigurasi saja"; **pos pantau/relawan** belum punya "lihat laporan sesuai penugasan"; **petugas** belum bisa melihat detail warga rentan "sesuai tugas".

## Iterasi 4 — PRD v2 (Riksa Warga, Kota Bandung, 5 role)

PRD terbaru: [`../PRD_RIKSA_WARGA.md`](../PRD_RIKSA_WARGA.md). **Skema berubah (role, status, tabel baru): jalankan `python -m scripts.seed --reset` sekali** (menghapus data demo lama).

| Role | Yang bisa dilakukan |
|---|---|
| **Warga** (`warga1-3`) | Izin lokasi **sekali** (dapat dicabut), lapor keselamatan (Saya Aman / Butuh Bantuan; tak menjawab di area berbahaya → *Diduga Butuh Bantuan*), lapor kejadian ke pos pantau, navigasi ke shelter, kondisi sungai & hujan + prediksi risiko, notifikasi |
| **Pos Pantau** (`pospantau1-2`) | 3 tombol kondisi sungai **Normal/Waspada/Meluap** (langsung tampil di semua role), antrean laporan + **pencocokan** dengan data sungai & hujan, verifikasi, **pengumuman** ke semua role non-admin (aplikasi + Telegram + SMS) beserta koreksinya, input tinggi air |
| **Koordinator Daerah** (`koord_rw01-02`) | Data keluarga warga, prioritas, ajukan bantuan ke Tim SAR, kelola shelter (Penuh → notifikasi ke Tim SAR, warga, pos pantau + shelter alternatif) |
| **Tim SAR** (`sar1-2`) | **Peta Bantuan** (warga butuh/diduga butuh bantuan; hanya saat Mode Bencana), terima tugas dari koordinator, **laporan pasca-bantuan** |
| **Admin** (`admin`) | Kelola pengguna + audit log (hanya itu) |

Fitur utama dan endpoint baru:

| Fitur | Endpoint / perilaku |
|---|---|
| Kondisi sungai 3 tingkat | `POST /stations/{id}/condition`; perubahan memicu alert (SMS hanya Waspada/Meluap); kondisi >6 jam tanpa pembaruan ditandai *belum diperbarui*; kondisi Waspada/Meluap pos hulu ikut dihitung sebagai bukti hulu di mesin eskalasi |
| Kondisi alam + prediksi | `GET /nature` (semua role kecuali admin): sungai berbagai daerah, tren, perkiraan waktu mencapai ambang, prakiraan hujan BMKG per kelurahan, **risiko banjir Rendah/Sedang/Tinggi + alasan + keyakinan**. Perkiraan berbasis aturan (bukan kepastian); ambang = asumsi uji |
| Notifikasi risiko naik | loop timer membandingkan risiko; kenaikan ke Sedang/Tinggi memicu alert (SMS hanya Tinggi), tidak berulang |
| Pencocokan laporan | `GET /reports/{id}/match` → sesuai / sebagian / tidak sesuai / data kurang (alat bantu; laporan tidak dihapus) |
| Pengumuman | `POST /announcements` (wajib laporan terverifikasi atau catatan pengamatan), `POST /announcements/{id}/correct` (alasan wajib, sampai ke penerima yang sama) |
| SMS | kanal baru di `services/notifier.py` (`SMS_MODE=mock|live`); log per kanal di `/alerts/{id}/deliveries`; admin tak pernah penerima |
| Izin lokasi sekali | `GET/POST/DELETE /me/location-consent`; lokasi terkini hanya disimpan bila ada izin dan hanya terlihat koordinator/Tim SAR saat **Mode Bencana** (sungai Meluap atau pengumuman meluap); dihapus otomatis setelah `LOCATION_RETENTION_HOURS` bila tak ada bencana |
| Diduga Butuh Bantuan | loop timer: warga ber-izin di zona (radius `DANGER_RADIUS_M` dari pos Meluap) yang tak menjawab `UNCONFIRMED_MINUTES` → status `duga_butuh_bantuan` (sumber `sistem`), alert internal ke koordinator + Tim SAR tanpa nama/lokasi |
| Peta Tim SAR | `GET /sar/needs` (diaudit) |
| Laporan pasca-bantuan | `POST /tasks/{id}/report`, `GET /tasks/{id}/reports` |
| Shelter nyata | `python -m scripts.import_shelters` mengimpor **kandidat** dari OpenStreetMap (titik kumpul, stadion/GOR, balai warga) sebagai *belum terverifikasi*; koordinator memverifikasi lewat aplikasi. Wilayah (`--region`, default RW 01) hanya pemetaan demo |
| BMKG | prakiraan per titik waktu 3 jam disimpan (`forecast_slots`); slot terdekat ±1,5 jam dipakai sebagai konteks cuaca |

Yang disengaja berbeda/dibatasi: lokasi latar belakang saat aplikasi tertutup tidak mungkin di PWA (lokasi dikirim saat aplikasi terbuka); pengiriman SMS sungguhan perlu penyedia (D-03); data shelter OSM bukan data resmi BPBD; koordinator mendapat akses **baca-saja** ke dashboard/kejadian sebagai tambahan di luar matriks PRD.

### Live Monitoring (simulator TMA tiap 3 detik)
- Tab **Live Monitoring** untuk Warga, Pos Pantau, Koordinator, Tim SAR: cuaca Kota Bandung asli dari **Open-Meteo** (cache 60 dtk) + tinggi muka air 7 pos (Hulu, Hilir, Cikapundung Gandok, Cikapundung Viaduct, Citepus Pagarsih, Cidurian Cicaheum, Retensi Gedebage). Koordinat pos baru = perkiraan, ambang = asumsi demo.
- TMA dibuat **simulator langsung** (`LIVE_SIM_SECONDS=3`, 0 = mati) dan berlabel SIMULASI karena sensor belum terpasang. Saat server start, riwayat 12 jam dibuat otomatis; data >13 jam dihapus.
- Klik nama pos → pop-up: TMA, status, tren, batas waspada/bahaya, grafik 12 jam, koordinat, Google Maps, navigasi shelter. **Pos pantau** mendapat tombol NORMAL / WASPADA / MELUAP yang langsung memindahkan data TMA dan kondisi (notifikasi + Mode Bencana ikut berubah di semua role).
- Endpoint: `GET /nature/live`, `GET /nature/stations/{id}`. Hujan Open-Meteo saat ini ikut menjadi faktor prediksi risiko.
- Setelah update kode: `python -m scripts.seed` (menambah 5 pos baru; tanpa `--reset`).
