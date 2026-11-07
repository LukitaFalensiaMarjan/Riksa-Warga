"""Matriks hak akses PRD v2 §5.2 untuk 5 peran terhadap API nyata.

Aksi tulis dikirim dengan payload sengaja salah / id tak ada, sehingga data tidak berubah:
403 = ditolak RBAC; 422/404 = lolos RBAC lalu ditolak validasi / tidak ditemukan.
Kolom urut: warga, koordinator, pos_pantau, tim_sar, admin.
"""
import pytest

USERS = ["warga1", "koord_rw01", "pospantau1", "sar1", "admin"]

SAR_REPORT = {"people_helped": 1, "condition": "selamat"}

CASES = [
    # (method, path, body, [status per peran])
    ("get", "/alerts", None, [200, 200, 200, 200, 200]),                                # lihat alert/pengumuman
    ("get", "/nature", None, [200, 200, 200, 200, 403]),                                # kondisi alam + prediksi: semua kecuali admin
    ("get", "/integrations", None, [200, 200, 200, 200, 200]),
    ("post", "/reports", {}, [422, 403, 422, 403, 403]),                                # warga lapor; pos pantau lapor kondisi daerah
    ("get", "/reports/mine", None, [200, 200, 200, 200, 200]),
    ("get", "/reports", None, [403, 403, 200, 403, 403]),                               # antrean laporan = pos pantau
    ("post", "/reports/999/verify", {}, [403, 403, 404, 403, 403]),                     # verifikasi: pos pantau saja
    ("post", "/reports/999/reject", {"reason": "bukan banjir"}, [403, 403, 404, 403, 403]),
    ("get", "/reports/999/match", None, [403, 403, 404, 403, 403]),                     # pencocokan sensor + cuaca
    ("post", "/announcements", {}, [403, 403, 422, 403, 403]),                          # pengumuman: pos pantau saja
    ("post", "/announcements/999/correct", {"reason": "salah"}, [403, 403, 404, 403, 403]),
    ("post", "/stations/999/condition", {}, [403, 403, 422, 403, 403]),                 # 3 tombol kondisi sungai
    ("post", "/stations/999/observations", {}, [403, 403, 422, 403, 403]),
    ("post", "/incidents/999/level", {"level": "waspada", "reason": "uji"}, [403, 403, 404, 403, 403]),
    ("post", "/incidents/999/cancel", {"reason": "salah deteksi"}, [403, 403, 404, 403, 403]),
    ("get", "/incidents", None, [403, 200, 200, 403, 403]),
    ("get", "/dashboard", None, [403, 200, 200, 403, 403]),
    ("get", "/residents", None, [403, 200, 403, 403, 403]),                             # data keluarga: koordinator
    ("get", "/evacuation/priorities", None, [403, 200, 403, 403, 403]),
    ("post", "/tasks", {}, [403, 422, 403, 403, 403]),                                  # ajukan bantuan SAR: koordinator
    ("post", "/tasks/999/report", SAR_REPORT, [403, 403, 403, 404, 403]),               # laporan pasca-bantuan: Tim SAR
    ("get", "/sar/needs", None, [403, 403, 403, 200, 403]),                             # peta warga butuh bantuan: Tim SAR
    ("post", "/shelters/999/status", {"status": "penuh"}, [403, 404, 403, 403, 403]),   # kelola shelter: koordinator
    ("get", "/shelters", None, [200, 200, 200, 200, 200]),
    ("get", "/me/location-consent", None, [200, 403, 403, 403, 403]),                   # izin lokasi: warga
    ("post", "/me/status", {}, [422, 403, 403, 403, 403]),                              # lapor keselamatan: warga
    ("get", "/users", None, [403, 403, 403, 403, 200]),                                 # kelola pengguna: admin
    ("post", "/users", {}, [403, 403, 403, 403, 422]),
    ("get", "/audit-logs", None, [403, 403, 403, 403, 200]),
    ("get", "/rules", None, [403, 200, 200, 403, 200]),
    ("put", "/rules/banjir", {}, [403, 403, 403, 403, 422]),
    ("put", "/weather", {}, [403, 422, 422, 403, 403]),
    ("post", "/integrations", {}, [403, 403, 403, 403, 422]),
    ("post", "/integrations/999/sync", None, [403, 403, 404, 403, 404]),
    ("post", "/simulation/stations/999/step", None, [403, 404, 404, 403, 403]),
]


@pytest.mark.parametrize("method,path,body,expected", CASES, ids=[f"{c[0]} {c[1]}" for c in CASES])
def test_prd_matrix(client, login, method, path, body, expected):
    wrong = []
    for user, want in zip(USERS, expected):
        kw = {} if body is None else {"json": body}
        got = getattr(client, method)(path, headers=login(user), **kw).status_code
        if got != want:
            wrong.append(f"{user}: dapat {got}, seharusnya {want}")
    assert not wrong, "; ".join(wrong)


def test_no_token_is_401(client):
    for method, path, body, _ in CASES:
        kw = {} if body is None else {"json": body}
        assert getattr(client, method)(path, **kw).status_code == 401, path
