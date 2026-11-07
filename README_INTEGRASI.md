# Riksa Warga — paket integrasi role Warga & Pos Pantau

Paket ini berisi dua folder:

| Folder | Isi |
|---|---|
| `role_warga/` | Aplikasi lengkap yang bisa langsung dijalankan + panduan `ROLE_WARGA.md` (semua fitur, endpoint, mekanisme, file, dan tes milik role **Warga**) |
| `role_pos_pantau/` | Aplikasi lengkap yang bisa langsung dijalankan + panduan `ROLE_POS_PANTAU.md` (semua fitur, endpoint, mekanisme, file, dan tes milik role **Pos Pantau**) |
| `PRD_RIKSA_WARGA.md` | PRD acuan |

## Kenapa tiap folder berisi aplikasi lengkap?

Fitur kedua role saling bergantung lewat **inti bersama** (database, login/RBAC, mesin kejadian, notifikasi
Telegram/SMS, simulator sungai). Contoh: laporan warga → diverifikasi pos pantau → pengumuman pos pantau → beranda
warga berubah merah. Kalau inti ini dipotong, fitur tidak bisa langsung dipakai. Jadi tiap folder dibuat
**berdiri sendiri** (bisa di-run tanpa folder lain), dan panduan per role menunjukkan persis bagian mana yang
menjadi milik role tersebut.

**Kode inti di kedua folder identik.** Saat menggabungkan ke proyek utama, cukup ambil inti dari salah satu folder,
lalu pakai panduan role untuk memastikan semua endpoint, service, tampilan, dan tes role tersebut ikut terbawa.

## Menjalankan (sama untuk kedua folder)

Butuh Python 3.11+ (diuji 3.13) dan MySQL 8 (mis. Laragon). Jalankan dari dalam folder role:

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/Mac: source .venv/bin/activate)
pip install -r requirements.txt
copy .env.example .env          # Linux/Mac: cp .env.example .env  -> lalu isi JWT_SECRET, DATABASE_URL, dll.
python -m scripts.seed          # buat database, tabel, dan data demo (aman diulang; tidak menghapus data)
python -m uvicorn app.main:app --reload
```

Buka http://127.0.0.1:8000. Akun demo: `warga1`, `warga2`, `warga3`, `pospantau1`, `pospantau2`,
`koord_rw01`, `koord_rw02`, `sar1`, `sar2`, `admin` — password = nilai `SEED_PASSWORD` di `.env`.

Cek cepat: http://127.0.0.1:8000/health → `telegram_mode` harus `live` bila ingin pesan benar-benar terkirim.
Nilai di `.env` mengalahkan variabel environment terminal.

Tes otomatis (tidak butuh MySQL, tidak pernah mengirim Telegram):

```bash
python -m pytest -q
```

## Yang sengaja TIDAK disertakan

- `.env` asli (berisi token bot Telegram & secret). Isi sendiri dari `.env.example`; minta token bot ke pemiliknya.
- `.venv`, `__pycache__`, `uploads/` (foto laporan), cache tes.

## Catatan data

- Tinggi muka air pos pantau berasal dari **simulator** (berlabel SIMULASI) karena sensor belum terpasang.
- Koordinat shelter dari OpenStreetMap; status resmi shelter perlu konfirmasi BPBD Kota Bandung.
- Ambang sungai, batas hujan, dan perkiraan peringatan dini adalah **asumsi uji**, bukan nilai resmi.
