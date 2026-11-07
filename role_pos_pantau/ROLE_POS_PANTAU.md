# Role POS PANTAU — fitur, mekanisme, dan peta file

Folder ini berisi aplikasi lengkap (bisa langsung di-run, lihat `README_INTEGRASI.md` di root zip). Dokumen ini
menandai bagian yang menjadi milik role **Pos Pantau** supaya tidak ada yang tertinggal saat integrasi.

Login demo: `pospantau1` (Pos Pantau Hulu), `pospantau2` (Pos Pantau Hilir); keduanya memantau seluruh kelurahan.
Menu pos pantau: Live Monitoring · Laporan Masuk · Pengumuman · Peta Evakuasi & Shelter · Lapor Kejadian · Peringatan.

## 1. Fitur & mekanisme

| Fitur | Mekanisme singkat |
|---|---|
| **Live Monitoring** | 7 pos pantau Kota Bandung. Simulator tinggi muka air (TMA) menulis 1 data per pos tiap `LIVE_SIM_SECONDS` (3 detik), riwayat 12 jam dibuat saat start. Status dari angka vs ambang: Normal / Waspada / Meluap. Popup detail: TMA, status, tren, grafik 12 jam, koordinat, ambang, Google Maps, navigasi shelter. |
| **Tombol kondisi (NORMAL/WASPADA/MELUAP)** | Di tiap kartu pos. Mengubah kondisi pos (`POST /stations/{id}/condition`), simulator langsung pindah ke pita nilai kondisi itu, dan alert **KONDISI** dikirim ke aplikasi + Telegram (SMS bila waspada/meluap). Meluap mengaktifkan Mode Bencana. |
| **Input tinggi air manual** | `POST /stations/{id}/observations` — lewat ambang → alert risiko internal. |
| **Laporan Masuk** | Kartu per laporan: judul, kondisi air, status, area pos pantau, waktu, **Rincian laporan** (pelapor, kondisi air, waktu kejadian/diterima, titik lokasi, GPS perangkat, data nyata/simulasi, foto, hal yang perlu dicek, waktu ditinjau), foto. Pos pantau memeriksa **manual** lalu menekan **Verifikasi** atau **Tolak** (langsung, tanpa isian). Laporan tidak pernah dihapus. |
| **Pengumuman (Buletin kondisi sungai)** | Overview live semua pos (TMA, status, tren, ambang) + **peringatan dini** per pos: meluap → banjir bantaran sangat mungkin/meluas; waspada → perkiraan jam ke ambang bahaya; normal tapi naik → perkiraan jam ke ambang waspada; hulu waspada/meluap → **banjir kiriman** ke pos hilir di sungai yang sama; hujan ≥1 mm/jam → faktor pendukung. Pratinjau pesan Telegram + catatan tambahan. Tombol **Siarkan** mengambil data live saat itu juga → alert PENGUMUMAN ke aplikasi + Telegram (SMS bila waspada/meluap). Riwayat terkirim + status pengiriman + koreksi/pembatalan. |
| **Kejadian (backend)** | Laporan dikelompokkan jadi kejadian; pos pantau bisa menetapkan level, verifikasi, batal, tutup (`/incidents/*`). Menu UI disembunyikan, endpoint tetap ada. |
| **Lapor Kejadian** | Sama seperti warga + centang "indikasi dari sensor pos pantau". |
| **Peringatan** | Semua alert + tombol "Status pengiriman Telegram" per alert. |
| **Pencocokan laporan (backend)** | `GET /reports/{id}/match` membandingkan laporan dengan angka TMA live pos (dan hujan sebagai pendukung). Tombol UI sudah dihapus atas permintaan; endpoint tetap ada. |

## 2. Endpoint API khusus / dipakai role Pos Pantau

| Method | Path | Akses |
|---|---|---|
| GET | `/reports` | pos pantau (laporan di wilayahnya) |
| POST | `/reports/{id}/verify`, `/reports/{id}/reject` | pos pantau |
| GET | `/reports/{id}/match` | pos pantau |
| POST | `/reports` | warga, pos pantau (`from_sensor` hanya pos pantau) |
| POST | `/stations/{id}/observations`, `/stations/{id}/condition` | pos pantau |
| GET | `/stations`, `/stations/{id}/trend`, `/nature`, `/nature/live`, `/nature/stations/{id}` | login non-admin |
| GET, POST | `/announcements/bulletin` | pos pantau (GET = overview + pratinjau, POST = siarkan) |
| POST | `/announcements`, `/announcements/{id}/correct` | pos pantau |
| GET | `/alerts`, `/alerts/{id}/deliveries` | login / pos pantau |
| GET | `/incidents`, `/incidents/{id}`, `/incidents/{id}/history` | koordinator, pos pantau |
| POST | `/incidents/{id}/level|verify|proposal/dismiss|cancel|close` | pos pantau |
| POST | `/simulation/stations/{id}/step` | koordinator, pos pantau |
| PUT | `/weather` | koordinator, pos pantau |
| POST | `/integrations/{id}/sync` | admin, pos pantau |
| GET | `/dashboard` | koordinator, pos pantau |
| POST | `/road-conditions` | koordinator, pos pantau, SAR |
| GET | `/shelters`, `/routing/shelter`, `/evacuation-routes`, `/road-conditions` | login |

## 3. File milik / dipakai role Pos Pantau

**Backend**
- `app/routers/reports.py` — `list_reports`, `verify_report`, `reject_report`, `match`
- `app/routers/stations.py` — observasi & tombol kondisi; `app/routers/nature.py` — live monitoring
- `app/routers/announcements.py` — buletin (`/announcements/bulletin`), pengumuman, koreksi
- `app/routers/incidents.py`, `app/routers/simulation.py`, `app/routers/context.py`, `app/routers/integrations.py`,
  `app/routers/dashboard.py`, `app/routers/alerts.py` (status pengiriman)
- `app/services/bulletin.py` — overview + peringatan dini + format pesan buletin
- `app/services/announce.py` — alert kondisi sungai, pengumuman, koreksi
- `app/services/live_sim.py` — simulator TMA 3 detik; `app/services/simulator.py` — langkah simulasi manual
- `app/services/monitoring.py` (status dari ambang, tren), `app/services/nature.py` (prediksi, ETA, live)
- `app/services/disaster.py` — kondisi 3 tingkat (`latest_condition`), Mode Bencana
- `app/services/matching.py` — pencocokan laporan (angka TMA live)
- `app/services/engine.py`, `app/services/rules.py`, `app/services/messages.py` — skor, kejadian, eskalasi, template
- `app/services/notifier.py` — kirim Telegram/SMS, penerima, status pengiriman
- `app/services/integrations.py` (BMKG), `app/services/weather_live.py` (Open-Meteo)
- `app/main.py` — loop simulator & tick eskalasi; peringatan bila `TELEGRAM_MODE` bukan `live`
- Model di `app/models.py`: `Station`, `Observation`, `RiverStatusLog`, `Report`, `Incident`, `Alert`, `AlertDelivery`

**Frontend** (`static/app.js`)
- `tabsFor("pos_pantau")` — daftar menu pos pantau
- `viewLive` + `tmaCard` (tombol kondisi di kartu) + `stationModal` — Live Monitoring
- `viewReports` + `reportsTable` — Laporan Masuk (Verifikasi/Tolak langsung, Rincian laporan)
- `viewAnnounce` — Pengumuman/buletin (overview, peringatan dini, pratinjau, siarkan, koreksi)
- `viewReport`, `viewMapNav`, `viewAlerts`

**Tes yang menjaga fitur pos pantau**
`tests/test_pos_pantau.py`, `tests/test_kondisi_pengumuman.py` (termasuk buletin), `tests/test_live_monitoring.py`,
`tests/test_prediksi.py` (pencocokan), `tests/test_engine.py`, `tests/test_simulator.py`, `tests/test_integrations.py`,
`tests/test_rbac_matrix.py`

## 4. Konfigurasi penting (`.env`)

- `TELEGRAM_MODE=live`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_DEFAULT_CHAT_ID` — tujuan semua alert publik
  (kondisi sungai, buletin). Penerima harus sudah mengirim `/start` ke bot.
- `LIVE_SIM_SECONDS=3` (0 = simulator mati), `ENGINE_TICK_SECONDS=30`.
- `SMS_MODE=mock` sampai penyedia SMS dipilih (adaptor di `app/services/notifier.py`).

## 5. Ketergantungan ke role lain (jangan dihapus saat integrasi)

- Laporan yang diperiksa berasal dari **warga** (`POST /reports`).
- Buletin, kondisi sungai, dan pengumuman diterima **warga, koordinator, Tim SAR** (bukan admin).
- Kondisi Meluap memicu Mode Bencana di sisi **warga** dan peta bantuan **Tim SAR**.
