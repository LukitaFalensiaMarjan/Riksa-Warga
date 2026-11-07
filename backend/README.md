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

Akun demo: `admin`, `koord_rw01`, `koord_rw02`, `pospantau1`, `pospantau2`, `relawan1`, `warga1`, `warga2`, `warga3`, semua memakai `SEED_PASSWORD` dari `.env`.
Seed juga membuat 2 pos pantau (hulu & hilir), 6 data warga (3 tanpa akun, 3 rentan), dan 3 shelter.

Telegram default `TELEGRAM_MODE=mock`: pengiriman hanya dicatat (status `mock`). Untuk kirim sungguhan isi `TELEGRAM_MODE=live`, `TELEGRAM_BOT_TOKEN`, dan `telegram_chat_id` akun penerima.

## Antarmuka web

Setelah `uvicorn` jalan, buka **http://127.0.0.1:8000/** (Swagger API tetap di `/docs`). Login dengan akun demo; tab yang muncul mengikuti peran:

| Peran | Tab |
|---|---|
| Warga / Relawan | Lapor Kejadian, Laporan Saya, Status Saya, Peringatan, Pos Pantau, Shelter |
| Pos Pantau | Pos Pantau (input tinggi air + grafik), Lapor Kejadian, Laporan Saya, Peringatan |
| Koordinator | Dashboard (peta), Kejadian, Laporan, Warga, Shelter, Pos Pantau, Cuaca & Aturan, Peringatan, Lapor |
| Admin | semua tab koordinator + Admin (akun, aturan, audit log) |

Form lapor punya "titik contoh" (Hulu 1-3, Hilir 1-3, Kebakaran) supaya demo cepat. Peta memakai Leaflet + OpenStreetMap dari internet.

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
