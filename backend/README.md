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
4. Buat database, tabel, wilayah demo, akun demo, dan shelter nyata Kota Bandung (OpenStreetMap):
   ```bash
   python -m scripts.seed --reset --demo-verify
   ```
   `--reset` MENGHAPUS semua tabel lalu membuat ulang (wajib setelah skema PRD v2). `--demo-verify` menandai shelter dalam radius 6 km dari lokasi demo sebagai terverifikasi hanya agar navigasi bisa dicoba; di lapangan koordinator yang memverifikasi.
5. Jalankan API, lalu buka http://127.0.0.1:8000/docs:
   ```bash
   uvicorn app.main:app --reload
   ```

Akun demo: `admin`, `koord_rw01`, `koord_rw02`, `pospantau1`, `pospantau2`, `timsar1`, `timsar2`, `warga1`, `warga2`, `warga3`, semua memakai `SEED_PASSWORD` dari `.env`.
Seed juga membuat 2 pos pantau (hulu & hilir), 6 data warga, 4 anggota keluarga, dan 59 kandidat shelter dari OpenStreetMap (belum terverifikasi kecuali `--demo-verify`).
Jalankan HANYA satu proses uvicorn (kunci mesin kejadian berlaku per proses).

Telegram default `TELEGRAM_MODE=mock`: pengiriman hanya dicatat (status `mock`). Untuk kirim sungguhan isi `TELEGRAM_MODE=live`, `TELEGRAM_BOT_TOKEN`, dan `telegram_chat_id` akun penerima.

## Antarmuka web

Setelah `uvicorn` jalan, buka **http://127.0.0.1:8000/** (Swagger API tetap di `/docs`). Login dengan akun demo; tab yang muncul mengikuti peran:

| Peran | Tab |
|---|---|
| Warga | Beranda (Mode Bencana, izin lokasi, Saya Aman / Butuh Bantuan, keluarga), Live, Prediksi, Peta Evakuasi, Laporan Saya, Peringatan, Shelter, Lapor |
| Koordinator | Dashboard, Live, Prediksi, Prioritas, Tugas Tim SAR, Data Warga, Data Keluarga, Peta & Rute, Shelter, Peringatan |
| Pos Pantau | Live (3 tombol kondisi sungai), Prediksi, Laporan & Verifikasi (pencocokan data), Kejadian & Level, Lapor, Peringatan (siaran + koreksi) |
| Tim SAR | Peta SAR (warga butuh bantuan), Tugas (ambil/terima/tolak/selesai + laporan pasca-bantuan), Live, Prediksi, Peta, Shelter, Peringatan |
| Admin | hanya Kelola User + audit log (hanya-baca) |

Peta memakai Leaflet + OpenStreetMap dari internet. Prakiraan hujan dari Open-Meteo (butuh internet; bila gagal tampil "tidak tersedia", bukan angka palsu). Data tinggi air simulator diberi label SIMULASI.

## SMS (Twilio)

Default `SMS_MODE=mock`: SMS hanya dicatat di status pengiriman. Untuk kirim sungguhan isi di `.env`:
```
SMS_MODE=twilio
TWILIO_ACCOUNT_SID=...
TWILIO_AUTH_TOKEN=...
TWILIO_FROM=+1xxxxxxxxxx        # atau TWILIO_MESSAGING_SERVICE_SID
```
Penerima harus: mengisi nomor ponsel di Profil, mencentang persetujuan SMS, dan nomor valid (08xx otomatis menjadi +628xx). SMS hanya untuk peristiwa berat (pengumuman pos pantau, kondisi sungai Waspada/Meluap, siaga/evakuasi, prediksi tinggi, permintaan bantuan). Batas `SMS_MAX_PER_HOUR` per nomor. Akun trial Twilio hanya bisa mengirim ke nomor yang sudah diverifikasi di konsol Twilio. Admin tidak pernah menerima peringatan.

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
| POST | `/reports` | login (laporan banjir/kebakaran; `from_sensor` hanya pos pantau) |
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
