"""Pengujian fitur Live Monitoring, Kontrol 3 Tombol Pos Pantau, dan Live Weather API."""
import pytest


def test_live_stations_accessible_to_all_roles(client, login):
    for user in ("warga1", "pospantau1", "relawan1", "koord_rw01", "admin"):
        r = client.get("/stations/live", headers=login(user))
        assert r.status_code == 200, f"Gagal untuk role {user}: {r.text}"
        data = r.json()
        assert isinstance(data, list)
        assert len(data) >= 1
        st = data[0]
        assert "current_condition" in st
        assert "warning_cm" in st
        assert "danger_cm" in st
        assert "river_name" in st


def test_pos_pantau_3_button_condition_override(client, login, ids):
    sid = ids["Pos Pantau Hulu"]

    # 1. Pos pantau tekan tombol WASPADA
    r1 = client.post(f"/stations/{sid}/condition", json={"condition": "waspada"}, headers=login("pospantau1"))
    assert r1.status_code == 200, r1.text
    res1 = r1.json()
    assert res1["condition"] == "waspada"
    assert res1["status"] in ("waspada", "bahaya")
    assert res1["level_cm"] >= 140

    # 2. Pos pantau tekan tombol MELUAP
    r2 = client.post(f"/stations/{sid}/condition", json={"condition": "meluap"}, headers=login("pospantau1"))
    assert r2.status_code == 200, r2.text
    res2 = r2.json()
    assert res2["condition"] == "meluap"
    assert res2["status"] == "bahaya"
    assert res2["level_cm"] >= 250

    # 3. Pos pantau tekan tombol NORMAL
    r3 = client.post(f"/stations/{sid}/condition", json={"condition": "normal"}, headers=login("pospantau1"))
    assert r3.status_code == 200, r3.text
    res3 = r3.json()
    assert res3["condition"] == "normal"
    assert res3["status"] == "normal"
    assert res3["level_cm"] < 150

    # 4. Warga tidak boleh override kondisi sungai (harus 403)
    r4 = client.post(f"/stations/{sid}/condition", json={"condition": "meluap"}, headers=login("warga1"))
    assert r4.status_code == 403


def test_live_weather_api_endpoint(client, login):
    r = client.get("/weather/live", headers=login("warga1"))
    assert r.status_code == 200, r.text
    w = r.json()
    assert "temperature_c" in w
    assert "humidity_pct" in w
    assert "precipitation_mm" in w
    assert "condition" in w
    assert "source" in w
    assert "Kota Bandung" in w["location"]


def test_tim_sar_role_functionality(client, login, ids):
    # Cek login relawan1 yang memiliki peran Role.TIM_SAR
    h = login("relawan1")
    assert h["Authorization"].startswith("Bearer ")

    # Tim SAR bisa akses daftar stasiun live
    r_live = client.get("/stations/live", headers=h)
    assert r_live.status_code == 200

    # Tim SAR bisa akses tugas
    r_tasks = client.get("/tasks", headers=h)
    assert r_tasks.status_code == 200

    # Tim SAR bisa akses shelters
    r_shelters = client.get("/shelters", headers=h)
    assert r_shelters.status_code == 200

    # Tim SAR bisa akses rescue targets
    r_targets = client.get("/evacuation/rescue-targets", headers=h)
    assert r_targets.status_code == 200
    assert "items" in r_targets.json()


def test_pos_pantau_verifies_report_and_broadcasts_alert(client, login, report, ids, set_chat):
    set_chat("warga1", "1001")
    # Warga buat laporan kejadian banjir
    rep = report("warga1", hazard="banjir", desc="Air sungai meluap di dekat permukiman")
    rep_id = rep["id"]

    # Pos Pantau bisa verifikasi laporan tersebut
    h_pos = login("pospantau1")
    r_verif = client.post(f"/reports/{rep_id}/verify", json={"note": "Dicocokkan dengan TMA sensor hulu"}, headers=h_pos)
    assert r_verif.status_code == 200
    assert r_verif.json()["status"] == "terverifikasi"

    # Pos Pantau siarkan pengumuman darurat (Broadcast ke Telegram & SMS)
    r_broad = client.post("/alerts/broadcast", json={
        "message": "STATUS SIAGA BANJIR: Aliran sungai Cikapundung meningkat. Warga harap siaga.",
        "level": "siaga"
    }, headers=h_pos)
    assert r_broad.status_code == 201
    alert_data = r_broad.json()
    assert "SIAGA BANJIR" in alert_data["message"]
    assert alert_data["level"] == "siaga"

    # Cek bahwa warga dapat melihat alert tersebut
    r_warga_alerts = client.get("/alerts", headers=login("warga1"))
    assert r_warga_alerts.status_code == 200
    assert any(a["id"] == alert_data["id"] for a in r_warga_alerts.json())

    # Cek deliveries untuk alert broadcast (memiliki kanal telegram dan sms)
    r_deliv = client.get(f"/alerts/{alert_data['id']}/deliveries", headers=h_pos)
    assert r_deliv.status_code == 200
    channels = {d["channel"] for d in r_deliv.json()}
    assert "telegram" in channels or "sms" in channels
