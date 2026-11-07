"""Alur inti PRD §9 & §21: pengelompokan, eskalasi, Evakuasi manual, batal/koreksi, Telegram."""
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select

from app.config import settings
from app.db import utcnow
from app.models import Alert, AlertDelivery, AlertLevel, Incident, Verification
from app.services import engine, notifier
from conftest import HILIR, HULU, aware

HULU_2 = (-6.8812, 107.6106)
HULU_3 = (-6.8798, 107.6095)
HILIR_2 = (-6.9008, 107.6155)
HILIR_3 = (-6.8998, 107.6146)


def _incident(client, login, incident_id, user="pospantau1"):
    return client.get(f"/incidents/{incident_id}", headers=login(user)).json()


def _alerts(db, incident_id):
    db.expire_all()
    return db.scalars(select(Alert).where(Alert.incident_id == incident_id).order_by(Alert.id)).all()


def _tick(db, minutes):
    db.expire_all()
    fired = engine.tick(db, utcnow() + timedelta(minutes=minutes))
    db.commit()
    notifier.deliver(db.get_bind(), [a.id for a in fired])
    return fired


def _weather(client, login, ids, mode="real", valid_until=None):
    body = {"region_id": ids["Kelurahan Demo"], "is_active": True, "description": "Peringatan hujan lebat",
            "source_mode": mode, "valid_until": valid_until}
    assert client.put("/weather", json=body, headers=login("pospantau1")).status_code == 200


# Pantau: 1 laporan -> internal saja
def test_single_report_is_internal_pantau(client, login, report, db, set_chat):
    set_chat("warga2", "1002")
    set_chat("pospantau1", "2001")
    r = report("warga1")
    inc = _incident(client, login, r["incident_id"])
    assert inc["level"] == "pantau" and inc["verification"] == "belum_diverifikasi"
    alerts = _alerts(db, inc["id"])
    assert [(a.kind.value, a.internal) for a in alerts] == [("pantau", True)]
    recipients = {d.recipient for d in db.scalars(select(AlertDelivery))}
    assert recipients == {"2001"}  # hanya koordinator


# FR-031: laporan berdekatan jadi satu kejadian, yang jauh jadi kejadian lain
def test_clustering_by_distance(report):
    a = report("warga1")
    b = report("warga2", at=HULU_2)
    c = report("warga3", at=HILIR)
    assert a["incident_id"] == b["incident_id"] != c["incident_id"]


# Waspada: usulan -> timeout -> otomatis berlabel belum diverifikasi
def test_waspada_auto_after_timeout(client, login, report, db, set_chat):
    for user, chat in (("warga1", "1001"), ("warga2", "1002"), ("warga3", "1003")):
        set_chat(user, chat)
    iid = report("warga1")["incident_id"]
    report("warga2", at=HULU_2)
    inc = _incident(client, login, iid)
    assert inc["level"] == "pantau" and inc["pending_level"] == "waspada"
    assert all(a.internal for a in _alerts(db, iid))

    assert _tick(db, 4) == []
    fired = _tick(db, 6)
    assert len(fired) == 1
    inc = _incident(client, login, iid)
    assert inc["level"] == "waspada" and inc["verification"] == "belum_diverifikasi"
    assert inc["pending_level"] is None
    public = [a for a in _alerts(db, iid) if not a.internal]
    assert "WASPADA BANJIR" in public[0].message and "BELUM DIVERIFIKASI" in public[0].message
    deliveries = db.scalars(select(AlertDelivery).where(AlertDelivery.alert_id == public[0].id)).all()
    assert {d.recipient for d in deliveries} == {"1001", "1002", "1003"}  # sekelurahan
    assert {d.status.value for d in deliveries} == {"mock"}
    history = client.get(f"/incidents/{iid}/history", headers=login("pospantau1")).json()
    assert "tidak ada respons koordinator" in history[-1]["new_value"]["pemicu"]


def test_coordinator_confirms_waspada(client, login, report):
    iid = report("warga1")["incident_id"]
    report("warga2", at=HULU_2)
    h = login("pospantau1")
    r = client.post(f"/incidents/{iid}/level", json={"level": "waspada", "reason": "Dicek RT, air naik 30 cm"},
                    headers=h)
    assert r.status_code == 200 and r.json()["kind"] == "level"
    inc = _incident(client, login, iid)
    assert inc["level"] == "waspada" and inc["verification"] == "terverifikasi" and inc["pending_level"] is None


def test_dismissed_proposal_does_not_fire(client, login, report, db):
    iid = report("warga1")["incident_id"]
    report("warga2", at=HULU_2)
    h = login("pospantau1")
    assert client.post(f"/incidents/{iid}/proposal/dismiss", json={}, headers=h).status_code == 422
    assert client.post(f"/incidents/{iid}/proposal/dismiss", json={"reason": "Genangan biasa, sudah surut"},
                       headers=h).status_code == 200
    assert _tick(db, 10) == []
    assert _incident(client, login, iid)["level"] == "pantau"


# PRD §21.3: laporan duplikat tidak dihitung sebagai pelapor independen
def test_duplicate_not_counted(client, login, report):
    iid = report("warga1")["incident_id"]
    dup = report("warga1", at=HULU_2)
    assert dup["status"] == "duplikat" and dup["incident_id"] == iid
    assert _incident(client, login, iid)["unique_reporters"] == 1


def test_new_report_after_rejection_is_counted(client, login, report):
    first = report("warga1")
    client.post(f"/reports/{first['id']}/reject", json={"reason": "Baru genangan biasa"},
                headers=login("pospantau1"))
    again = report("warga1", at=HULU_2)  # orang sama, <200 m, <30 menit
    assert again["status"] == "diterima"
    assert _incident(client, login, again["incident_id"])["unique_reporters"] == 1


def test_old_event_time_flagged_and_not_counted(client, login, report):
    iid = report("warga1")["incident_id"]
    old = report("warga2", at=HULU_2, reported_at=aware(utcnow() - timedelta(hours=7)))
    detail = client.get(f"/reports/{old['id']}", headers=login("pospantau1")).json()
    assert "waktu_laporan_lama" in detail["flags"]
    assert _incident(client, login, iid)["unique_reporters"] == 1


def test_auto_waspada_keeps_human_verification(client, login, report, db):
    iid = report("warga1")["incident_id"]
    report("warga2", at=HULU_2)
    h = login("pospantau1")
    r = client.post(f"/incidents/{iid}/verify", json={"note": "Ketua RT cek lokasi"}, headers=h)
    assert r.status_code == 200 and r.json()["verification"] == "terverifikasi"
    _tick(db, 6)
    inc = _incident(client, login, iid)
    assert inc["level"] == "waspada" and inc["verification"] == "terverifikasi"
    msg = [a for a in _alerts(db, iid) if not a.internal][-1].message
    assert "WASPADA — TERVERIFIKASI" in msg
    client.post(f"/incidents/{iid}/close", json={"reason": "Air surut"}, headers=h)
    assert client.post(f"/incidents/{iid}/verify", json={}, headers=h).status_code == 409


def test_rejecting_report_withdraws_waspada_proposal(client, login, report, db):
    iid = report("warga1")["incident_id"]
    second = report("warga2", at=HULU_2)
    assert _incident(client, login, iid)["pending_level"] == "waspada"
    client.post(f"/reports/{second['id']}/reject", json={"reason": "Foto dari kejadian tahun lalu"},
                headers=login("pospantau1"))
    assert _incident(client, login, iid)["pending_level"] is None
    assert _tick(db, 10) == []
    assert _incident(client, login, iid)["level"] == "pantau"


def test_gps_mismatch_flagged_and_not_counted(client, login, report):
    iid = report("warga1")["incident_id"]
    far = report("warga2", at=HULU_2, gps_lat=-6.95, gps_lng=107.70)
    detail = client.get(f"/reports/{far['id']}", headers=login("pospantau1")).json()
    assert "lokasi_tidak_cocok" in detail["flags"]
    assert _incident(client, login, iid)["unique_reporters"] == 1
    # setelah koordinator verifikasi, laporan dihitung
    client.post(f"/reports/{far['id']}/verify", json={"note": "Ditelepon, GPS HP salah"}, headers=login("pospantau1"))
    assert _incident(client, login, iid)["unique_reporters"] == 2


# Siaga banjir: 3 pelapor + hulu + cuaca (PRD §9.3)
def test_flood_siaga_auto_unverified(client, login, report, ids, db):
    _weather(client, login, ids)
    iid = report("warga1")["incident_id"]
    report("warga2", at=HULU_2)
    report("warga3", at=HULU_3)
    inc = _incident(client, login, iid)
    assert inc["level"] == "siaga" and inc["verification"] == "belum_diverifikasi"
    msg = [a for a in _alerts(db, iid) if not a.internal][-1].message
    assert "SIAGA BANJIR" in msg and "BELUM DIVERIFIKASI" in msg and "BUKAN perintah evakuasi" in msg
    factors = {f["faktor"] for f in inc["reports"][0]["score_factors"]}
    assert {"hulu", "cuaca", "pelapor_lain"} <= factors


def test_expired_weather_ignored(client, login, report, ids):
    _weather(client, login, ids, valid_until=aware(utcnow() - timedelta(hours=1)))
    iid = report("warga1")["incident_id"]
    report("warga2", at=HULU_2)
    report("warga3", at=HULU_3)
    inc = _incident(client, login, iid)
    assert inc["level"] == "pantau"
    assert "cuaca" not in {f["faktor"] for f in inc["reports"][0]["score_factors"]}


# FR-012: simulasi tidak pernah bercampur dengan kejadian nyata
def test_simulation_kept_apart_from_real(client, login, report, ids):
    _weather(client, login, ids, mode="simulation")
    client.post(f"/stations/{ids['Pos Pantau Hulu']}/observations",
                json={"level_cm": 200, "source_mode": "simulation"}, headers=login("pospantau1"))
    real = report("warga1", at=HILIR)["incident_id"]
    report("warga2", at=HILIR_2)
    report("warga3", at=HILIR_3)
    prank = report("pospantau2", at=HILIR, source_mode="simulation")
    assert prank["incident_id"] != real

    inc = _incident(client, login, real)
    assert inc["is_simulation"] is False and inc["unique_reporters"] == 3
    assert inc["level"] == "pantau"  # cuaca & pos hulu simulasi tidak dihitung
    factors = {f["faktor"] for f in inc["reports"][0]["score_factors"]}
    assert not factors & {"cuaca", "pos_pantau_ambang"}

    # skenario demo: semua simulasi -> bukti simulasi berlaku dan berlabel [SIMULASI]
    sim = report("warga1", at=HILIR, source_mode="simulation")["incident_id"]
    assert sim == prank["incident_id"]
    report("warga2", at=HILIR_2, source_mode="simulation")
    sim_inc = _incident(client, login, sim)
    assert sim_inc["level"] == "siaga" and sim_inc["is_simulation"] is True
    msgs = client.get(f"/alerts?incident_id={sim}", headers=login("pospantau1")).json()
    assert all(m["message"].startswith("[SIMULASI]") for m in msgs)
    assert all(not m["message"].startswith("[SIMULASI]")
               for m in client.get(f"/alerts?incident_id={real}", headers=login("pospantau1")).json())


# FR-035: cuaca bukan bukti tunggal
def test_weather_alone_does_not_escalate(client, login, report, ids):
    _weather(client, login, ids)
    iid = report("warga1")["incident_id"]
    inc = _incident(client, login, iid)
    assert inc["level"] == "pantau" and inc["pending_level"] is None


def test_no_upstream_no_siaga(client, login, report, ids):
    _weather(client, login, ids)
    iid = report("warga1", at=HILIR)["incident_id"]
    report("warga2", at=HILIR_2)
    report("warga3", at=HILIR_3)
    inc = _incident(client, login, iid)
    assert inc["unique_reporters"] == 3
    assert inc["level"] == "pantau" and inc["pending_level"] == "waspada"


def test_upstream_station_alarm_counts_as_upstream(client, login, report, ids):
    _weather(client, login, ids)
    iid = report("warga1", at=HILIR)["incident_id"]
    report("warga2", at=HILIR_2)
    report("warga3", at=HILIR_3)
    client.post(f"/stations/{ids['Pos Pantau Hulu']}/observations", json={"level_cm": 180},
                headers=login("pospantau1"))
    assert _incident(client, login, iid)["level"] == "siaga"


def test_weather_activation_after_reports_triggers_siaga(client, login, report, ids):
    iid = report("warga1")["incident_id"]
    report("warga2", at=HULU_2)
    report("warga3", at=HULU_3)
    assert _incident(client, login, iid)["level"] == "pantau"
    _weather(client, login, ids)
    assert _incident(client, login, iid)["level"] == "siaga"


# Evakuasi tidak pernah otomatis
def test_engine_never_sets_evakuasi(client, login, report, ids, db):
    _weather(client, login, ids)
    iid = report("warga1")["incident_id"]
    for user, at in (("warga2", HULU_2), ("warga3", HULU_3), ("pospantau1", HULU), ("pospantau2", HULU_2)):
        report(user, at=at)
    _tick(db, 60)
    assert _incident(client, login, iid)["level"] == "siaga"
    inc = db.get(Incident, iid)
    with pytest.raises(RuntimeError):
        engine._apply_level(db, inc, AlertLevel.EVAKUASI, actor_id=None, trigger="tes", reason=None,
                            verification=Verification.BELUM, now=utcnow())
    db.rollback()


def test_manual_evakuasi_rules(client, login, report, ids, db):
    iid = report("warga1")["incident_id"]
    report("warga2", at=HULU_2)
    h = login("pospantau1")
    client.post(f"/incidents/{iid}/level", json={"level": "waspada", "reason": "Konfirmasi lapangan"}, headers=h)
    r = client.post(f"/incidents/{iid}/level", json={"level": "evakuasi", "reason": "Air deras"}, headers=h)
    assert r.status_code == 409  # harus Siaga dulu
    client.post(f"/incidents/{iid}/level", json={"level": "siaga", "reason": "Air terus naik"}, headers=h)
    assert client.post(f"/incidents/{iid}/level", json={"level": "evakuasi"}, headers=h).status_code == 422
    assert client.post(f"/incidents/{iid}/level", json={"level": "evakuasi", "reason": "Instruksi BPBD"},
                       headers=login("koord_rw01")).status_code == 403
    r = client.post(f"/incidents/{iid}/level", json={"level": "evakuasi", "reason": "Instruksi BPBD via telepon"},
                    headers=h)
    assert r.status_code == 200
    msg = r.json()["message"]
    assert "EVAKUASI BANJIR" in msg and "Sasana Budaya Ganesha (Sabuga ITB)" in msg and "Taman Gasibu" not in msg
    assert r.json()["verification"] == "terverifikasi"


# FR-037, FR-044: koreksi & pembatalan
def test_correction_lowering_level(client, login, report):
    iid = report("warga1")["incident_id"]
    h = login("pospantau1")
    client.post(f"/incidents/{iid}/level", json={"level": "siaga", "reason": "Cek lapangan"}, headers=h)
    r = client.post(f"/incidents/{iid}/level", json={"level": "waspada", "reason": "Air mulai surut"}, headers=h)
    assert r.json()["kind"] == "koreksi"
    assert "KOREKSI BANJIR" in r.json()["message"] and "Air mulai surut" in r.json()["message"]


def test_cancel_reaches_previous_recipients_and_keeps_history(client, login, report, db, set_chat):
    set_chat("warga1", "1001")
    set_chat("warga2", "1002")
    iid = report("warga1")["incident_id"]
    h = login("pospantau1")
    first = client.post(f"/incidents/{iid}/level", json={"level": "waspada", "reason": "Cek lapangan"},
                        headers=h).json()
    set_chat("warga2", None)  # warga2 keluar dari daftar Telegram setelah menerima alert
    assert client.post(f"/incidents/{iid}/cancel", json={}, headers=h).status_code == 422
    r = client.post(f"/incidents/{iid}/cancel", json={"reason": "Laporan keliru, air dari pipa bocor"}, headers=h)
    assert r.status_code == 200 and r.json()["kind"] == "pembatalan" and r.json()["internal"] is False
    db.expire_all()
    cancel_to = {d.recipient for d in db.scalars(select(AlertDelivery).where(AlertDelivery.alert_id == r.json()["id"]))}
    assert cancel_to == {"1001", "1002"}
    assert db.get(Alert, first["id"]) is not None  # alert lama tidak dihapus
    assert _incident(client, login, iid)["status"] == "dibatalkan"
    assert client.post(f"/incidents/{iid}/level", json={"level": "siaga", "reason": "x" * 5},
                       headers=h).status_code == 409
    actions = [x["action"] for x in client.get(f"/incidents/{iid}/history", headers=h).json()]
    assert actions == ["incident.level", "incident.dibatalkan"]


def test_cancel_without_public_alert_stays_internal(client, login, report):
    iid = report("warga1")["incident_id"]
    r = client.post(f"/incidents/{iid}/cancel", json={"reason": "Salah lapor"}, headers=login("pospantau1"))
    assert r.json()["internal"] is True


def test_close_incident(client, login, report):
    iid = report("warga1")["incident_id"]
    h = login("pospantau1")
    client.post(f"/incidents/{iid}/level", json={"level": "waspada", "reason": "Cek lapangan"}, headers=h)
    r = client.post(f"/incidents/{iid}/close", json={"reason": "Air surut, semua warga terdata"}, headers=h)
    assert r.json()["kind"] == "selesai" and "TERKENDALI/SELESAI" in r.json()["message"]
    assert client.get("/incidents", headers=h).json() == []


# PRD §21.3: Telegram gagal -> dicatat, alert tetap ada
def test_telegram_failure_recorded(client, login, report, db, set_chat, monkeypatch):
    set_chat("warga1", "1001")
    monkeypatch.setattr(settings, "telegram_mode", "live")
    monkeypatch.setattr(settings, "telegram_bot_token", "123:RAHASIA")

    def boom(*a, **k):
        raise httpx.ConnectError("gagal ke https://api.telegram.org/bot123:RAHASIA/sendMessage")

    monkeypatch.setattr(httpx, "post", boom)
    iid = report("warga1")["incident_id"]
    r = client.post(f"/incidents/{iid}/level", json={"level": "waspada", "reason": "Cek lapangan"},
                    headers=login("pospantau1"))
    assert r.status_code == 200
    db.expire_all()
    d = db.scalars(select(AlertDelivery).where(AlertDelivery.alert_id == r.json()["id"])).one()
    assert d.status.value == "gagal" and "RAHASIA" not in d.error
    shown = client.get(f"/alerts/{r.json()['id']}/deliveries", headers=login("pospantau1")).json()
    assert shown[0]["status"] == "gagal"
    assert any(a["id"] == r.json()["id"] for a in client.get("/alerts", headers=login("warga1")).json())


# PRD §18.1: data warga rentan tidak masuk pesan alert
def test_vulnerable_data_never_in_messages(client, login, report, ids, db):
    _weather(client, login, ids)
    iid = report("warga1")["incident_id"]
    report("warga2", at=HULU_2)
    report("warga3", at=HULU_3)
    client.post(f"/residents/{ids['Mbah Sutini']}/status",
                json={"status": "butuh_bantuan", "need_type": "evakuasi"}, headers=login("pospantau1"))
    client.post(f"/incidents/{iid}/level", json={"level": "evakuasi", "reason": "Instruksi BPBD"},
                headers=login("pospantau1"))
    for a in db.scalars(select(Alert)):
        assert "kursi roda" not in a.message and "Mbah Sutini" not in a.message


# PRD §21.2: banjir dengan indikasi sensor simulasi dari pos pantau
def test_flood_flow_with_simulated_sensor(client, login, report, ids):
    iid = report("warga1", source_mode="simulation")["incident_id"]
    s = report("pospantau1", from_sensor=True, source_mode="simulation", at=(-6.8812, 107.6101))
    assert s["incident_id"] == iid
    inc = _incident(client, login, iid)
    assert inc["is_simulation"] is True and inc["unique_reporters"] == 2
    r = client.post(f"/incidents/{iid}/level", json={"level": "siaga", "reason": "Air naik terlihat dari pos"},
                    headers=login("pospantau1")).json()
    assert r["message"].startswith("[SIMULASI]") and "SIAGA BANJIR" in r["message"]
