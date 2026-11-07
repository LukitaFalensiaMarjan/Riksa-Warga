# Plan Backend — Riksa Warga

Sumber: `PRD_SALING_JAGA.md`. Fokus: backend / fungsi tiap fitur. Frontend menyusul.

## Stack

| Lapisan | Pilihan |
|---|---|
| API | FastAPI |
| ORM | SQLAlchemy 2 |
| Database | **MySQL 8** (Laragon lokal), driver `pymysql`, charset `utf8mb4` |
| Auth | JWT (PyJWT) + bcrypt |
| Notifikasi | Telegram Bot API via `httpx`, mode `mock` untuk demo offline |
| Timer eskalasi | background loop asyncio di dalam app |
| Realtime | polling `GET /events?since=` |
| Tes | pytest + TestClient, SQLite in-memory (model dijaga portabel) |

Catatan MySQL:
- Semua kolom teks memakai `String(n)` eksplisit (MySQL butuh panjang VARCHAR).
- Waktu disimpan sebagai UTC naive `DATETIME`.
- `pool_pre_ping` + `pool_recycle` agar koneksi tidak putus karena `wait_timeout`.
- Skema dibuat lewat `create_all` di `scripts/seed.py`. Alembic menyusul bila skema mulai berubah setelah ada data nyata.
- Tes jalan di SQLite. Satu kali smoke test manual ke MySQL wajib per fase.

## Struktur

```
backend/
  app/main.py, config.py, db.py, models.py, schemas.py
  app/auth.py        # JWT, get_current_user, require_role, akses wilayah
  app/audit.py       # log_action(...)
  app/routers/       # auth, users, regions (+ reports, monitoring, incidents, alerts, residents, tasks, shelters, dashboard)
  app/services/      # scoring, clustering, escalation, notifier, templates (Fase 2+)
  scripts/seed.py
  tests/
```

## Fase

| Fase | Isi | FR | Estimasi |
|---|---|---|---|
| 0 Fondasi | config, DB MySQL, model User/Region/AuditLog, login JWT, RBAC, akses wilayah, admin kelola akun, seed wilayah demo | 001–004 | 3 jam |
| 1 Laporan & Monitoring | laporan banjir/kebakaran + foto, pos pantau, sensor REAL/SIMULATION, cek duplikat, tren tinggi air | 012, 015–016, 020–026 | 4 jam |
| 2 Engine | skor + rincian faktor, pengelompokan haversine, `rule_config`, eskalasi Pantau→Waspada→Siaga, Evakuasi hanya manual, riwayat level | 030–037 | 5 jam |
| 3 Alert | template, Telegram + AlertDelivery, batal/koreksi dengan alasan | 040–045 | 3 jam |
| 4 Rescue | warga + profil rentan terbatas, ResidentStatus append-only, Saya Aman/Butuh Bantuan, state machine tugas | 060–074 | 4 jam |
| 5 Peta & Dashboard | GeoJSON, shelter, ringkasan, `/events` | 010–011, 050–051, 054 | 2 jam |
| 6 Demo | `simulate.py flood|fire`, tes e2e + skenario gagal | §21 | 3 jam |

## Iterasi 1 — Fokus Warga, Koordinator RT/RW, Pos Pantau

Relawan, petugas, dan penugasan tugas (FR-070–074) ditunda. Kebutuhan "Butuh Bantuan" ditangani koordinator lewat pembaruan status warga (Dalam Penanganan → Tiba di Titik Aman).

### Warga
| Fungsi | Endpoint | FR |
|---|---|---|
| Lapor banjir/kebakaran (lokasi pin + GPS opsional, waktu, jenis indikasi) | `POST /reports` | 020, 022, 024 |
| Lampirkan foto (JPG/PNG/WebP, ≤5 MB, cek magic bytes, SHA-256) | `POST /reports/{id}/photo` | 021 |
| Lihat status laporan sendiri + alasan | `GET /reports/mine` | 027 |
| Kirim "Saya Aman" / "Butuh Bantuan" + jenis kebutuhan | `POST /me/status` | 062, 063 |
| Lihat alert publik wilayahnya (bukan internal) | `GET /alerts` | RBAC |
| Lihat shelter terverifikasi | `GET /shelters` | 051 |

### Pos Pantau
| Fungsi | Endpoint | FR |
|---|---|---|
| Kirim tinggi air + kondisi sungai (REAL/SIMULATION) | `POST /stations/{id}/observations` | 023, 012 |
| Tren naik/stabil/turun, status vs ambang, tanda data kedaluwarsa | `GET /stations/{id}/trend` | 015 |
| Indikasi sensor kebakaran (sumber `sensor`) | `POST /reports` dengan `from_sensor` | 016, 024 |
| Lintas ambang waspada/bahaya → notifikasi risiko internal (bukan bukti banjir) | otomatis | 9.1 |

### Koordinator RT/RW
| Fungsi | Endpoint | FR |
|---|---|---|
| Dashboard: kejadian aktif, laporan 24 jam per status/sumber, pos pantau, cuaca, status warga | `GET /dashboard` | 010, 011 |
| Laporan + skor + rincian faktor; verifikasi/tolak (alasan wajib) | `GET /reports`, `POST /reports/{id}/verify\|reject` | 030, 032 |
| Kejadian: kelompok laporan, level, label verifikasi, riwayat | `GET /incidents`, `/incidents/{id}/history` | 031, 033, 036 |
| Konfirmasi/tolak usulan Waspada, ubah level, Evakuasi manual, batal, selesai | `POST /incidents/{id}/...` | 037 |
| Konteks cuaca (input manual BMKG / simulasi) | `PUT /weather` | 035 |
| Data warga, penanda rentan (wajib consent), detail sensitif diaudit | `/residents` | 060, 061 |
| Status warga tanpa smartphone, antrean Butuh Bantuan, rekap | `/residents/{id}/status`, `/help-requests`, `/residents/summary` | 064, 065 |
| Shelter: tambah, verifikasi, ubah status | `/shelters` | 051, 054 |

### Mesin aturan (PRD §9.3, parameter di tabel `rule_configs`)
- 1 laporan → kejadian **Pantau**, notifikasi internal koordinator.
- ≥2 pelapor unik dalam radius → **usulan Waspada**. Koordinator konfirmasi/tolak; tanpa respons N menit → Waspada otomatis berlabel BELUM DIVERIFIKASI.
- Banjir ≥3 pelapor unik + hulu (laporan dekat pos hulu atau pos hulu ≥ ambang) + cuaca aktif → **Siaga** otomatis BELUM DIVERIFIKASI. Kebakaran: ≥3 pelapor unik.
- **Evakuasi** hanya manual koordinator, setelah Siaga, alasan wajib.
- Tidak dihitung sebagai pelapor unik: duplikat, ditolak, dan laporan bertanda pemeriksaan (foto pernah dipakai, GPS ≠ pin >1 km, waktu laporan >6 jam) sampai diverifikasi.
- Telegram mode `mock` default; `live` butuh token. Pembatalan/koreksi dikirim ke penerima sebelumnya + audiens sekarang.

### Tes
`tests/test_warga.py`, `tests/test_pos_pantau.py`, `tests/test_koordinator.py`, `tests/test_engine.py` (alur banjir & kebakaran PRD §21).

## Iterasi 2 — Finishing (semua peran + evakuasi + rute + offline + UI)

### A. Relawan & penugasan (FR-070–074)
- Tabel `rescue_tasks`: jenis (evakuasi/medis/logistik/damkar/sar/lainnya), prioritas, lokasi, warga terkait, relawan, shelter tujuan, status, hasil.
- Alur status (PRD §12.3): `menunggu_penerimaan → diterima → menuju_lokasi → dalam_penanganan → selesai`; `gagal` dan `dibatalkan` wajib alasan.
- Relawan hanya melihat & mengubah tugasnya sendiri; koordinator membuat, menugaskan ulang, membatalkan.
- Efek ke status warga: diterima/menuju → `dalam_penanganan`; selesai + shelter → `tiba_di_titik_aman` + check-in shelter; gagal → kembali `butuh_bantuan`.

### B. Lokasi warga & prioritas evakuasi
- Lokasi rumah (diisi koordinator/warga) dan lokasi terkini yang **dibagikan warga secara sadar** (tombol, atau ikut saat "Butuh Bantuan"). Bukan pelacakan GPS terus-menerus (di luar ruang lingkup PRD §5.4).
- Skor prioritas transparan: status keselamatan, kerentanan, tanpa smartphone, jenis kebutuhan, jarak ke kejadian, level kejadian, lama menunggu → label **Kritis / Tinggi / Sedang / Rendah** beserta faktornya. Alat bantu, bukan keputusan.
- Peta prioritas hanya untuk koordinator wilayahnya; setiap akses dicatat di audit log. Lokasi tidak pernah masuk pesan Telegram.

### C. Rute ke shelter (seperti peta navigasi)
- Backend memanggil OSRM jalan kaki (`ROUTING_URL`, default routing.openstreetmap.de) ke 1–2 shelter terverifikasi terdekat yang masih tersedia; gagal → garis lurus berlabel jelas.
- Titik bahaya jalan (FR-052: tertutup, genangan, api, pohon tumbang, kabel) dan kejadian aktif dicek terhadap rute → peringatan; rute alternatif dipilih bila ada.
- Rute evakuasi resmi digambar koordinator di peta (FR-053) dengan status validasi. Label "aman" hanya untuk rute **terverifikasi**; rute OSRM selalu "belum diverifikasi".
- Mode navigasi: posisi GPS langsung di peta, jarak tersisa, arah ke shelter.

### D. Offline (pendekatan bertahap, jujur soal batas)
- PWA: service worker menyimpan aplikasi, data shelter/rute/alert terakhir (network-first, berlabel waktu data), dan tile peta yang **pernah dibuka** (OSM tidak mengizinkan unduh massal; area offline penuh ala Tapaki butuh server tile sendiri / PMTiles — roadmap).
- Saat offline: peta tersimpan + titik GPS + rute terakhir + rute resmi + arah & jarak garis lurus ke shelter.
- Antrean laporan offline di perangkat dengan `client_ref` unik → dikirim saat online, tanpa duplikat (PRD §15.1).

### E. Lain-lain
- Check-in shelter & okupansi (FR-067), cetak daftar warga/tugas (FR-085), `scripts.seed --reset`.

### F. UI/UX
- Logo dari pengguna, palet dari logo (navy, biru, teal, hijau), font Plus Jakarta Sans.
- Beranda warga: banner level, tombol besar **Saya Aman / Butuh Bantuan / Lapor**, shelter terdekat + rute.
- Mobile-first, status selalu berupa teks + warna (PRD §16.5).

### G. Tes
- `test_tasks.py`, `test_evacuation.py`, `test_routing.py` (OSRM di-mock), offline `client_ref`, check-in; uji UI di browser pada DB SQLite terpisah.

## Aturan keselamatan yang dikunci di kode

- Engine otomatis tidak pernah menaikkan level ke Evakuasi (ada tes).
- Laporan skor rendah tidak pernah dihapus.
- Status warga default Belum Terkonfirmasi; Saya Aman ≠ Aman Terverifikasi.
- Data simulasi berlabel `SIMULATION`.
- Batal/koreksi alert wajib alasan, dikirim ke penerima yang sama, histori tetap.
- Data warga rentan tidak masuk pesan Telegram.

## Risiko

- TINGGI: bug timer eskalasi → plafon Siaga dikunci + tes.
- TINGGI: waktu → Fase 2–3 prioritas, Fase 5 boleh dipangkas.
- SEDANG: perbedaan perilaku SQLite (tes) vs MySQL (run) → smoke test MySQL tiap fase.
- SEDANG: internet Telegram saat demo → mode mock.
- SEDANG: bobot skor tanpa dasar ilmiah → konfigurasi berlabel asumsi.
