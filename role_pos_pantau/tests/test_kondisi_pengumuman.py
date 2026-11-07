"""PRD v2: kondisi sungai 3 tombol, pengumuman pos pantau, notifikasi Telegram + SMS (FR-020, FR-028/029, FR-040–046)."""
from datetime import timedelta

import httpx
from sqlalchemy import select

from app.config import settings
from app.db import utcnow
from app.models import Alert, AlertDelivery, AlertKind, DeliveryStatus, RiverStatusLog
from app.services import notifier
from conftest import HILIR

HILIR_2 = (-6.9008, 107.6155)
HILIR_3 = (-6.8998, 107.6146)
ALL = (("warga1", 1), ("warga3", 3), ("koord_rw01", 4), ("pospantau2", 5), ("sar1", 6))


def _cond(client, login, ids, status, user="pospantau1", station="Pos Pantau Hulu", expect=201, **extra):
    r = client.post(f"/stations/{ids[station]}/condition", json={"status": status, **extra}, headers=login(user))
    assert r.status_code == expect, r.text
    return r.json()


def _contacts(set_chat, set_phone, users=ALL):
    for username, n in users:
        set_chat(username, f"100{n}")
        set_phone(username, f"+62811000{n}")


def _deliveries(db, channel):
    db.expire_all()
    return {d.recipient for d in db.scalars(select(AlertDelivery).where(AlertDelivery.channel == channel))}


# ---------- kondisi sungai ----------
def test_condition_buttons_visible_to_every_role(client, login, ids):
    out = _cond(client, login, ids, "waspada", note="Air mulai naik")
    assert out["condition"]["status"] == "waspada"
    for user in ("warga1", "koord_rw01", "pospantau2", "sar1"):
        stations = {s["name"]: s for s in client.get("/stations", headers=login(user)).json()}
        c = stations["Pos Pantau Hulu"]["condition"]
        assert c["status"] == "waspada" and c["stale"] is False and c["source_mode"] == "real"
        assert stations["Pos Pantau Hilir"]["condition"] is None  # belum pernah diatur
    assert client.post(f"/stations/{ids['Pos Pantau Hulu']}/condition", json={"status": "banjir_besar"},
                       headers=login("pospantau1")).status_code == 422


def test_condition_change_notifies_all_roles_except_admin_via_telegram_and_sms(client, login, ids, db, set_chat,
                                                                                set_phone):
    _contacts(set_chat, set_phone, ALL + (("admin", 9),))
    _cond(client, login, ids, "waspada")
    db.expire_all()
    alert = db.scalar(select(Alert).where(Alert.kind == AlertKind.KONDISI))
    assert alert.sms and not alert.internal and alert.severity == "waspada"
    assert "KONDISI SUNGAI: WASPADA" in alert.message and "bukan perintah evakuasi" not in alert.message.lower()
    assert _deliveries(db, "telegram") == {"1001", "1003", "1004", "1005", "1006"}  # tanpa admin (1009)
    assert _deliveries(db, "sms") == {f"+62811000{n}" for n in (1, 3, 4, 5, 6)}
    assert {d.status for d in db.scalars(select(AlertDelivery))} == {DeliveryStatus.MOCK}


def test_same_condition_is_deduplicated_and_normal_has_no_sms(client, login, ids, db):
    _cond(client, login, ids, "waspada")
    _cond(client, login, ids, "waspada")  # sama: tidak mengirim ulang
    _cond(client, login, ids, "normal")
    db.expire_all()
    alerts = db.scalars(select(Alert).where(Alert.kind == AlertKind.KONDISI).order_by(Alert.id)).all()
    assert [a.severity for a in alerts] == ["waspada", "normal"]
    assert [a.sms for a in alerts] == [True, False]  # SMS hanya untuk Waspada/Meluap
    assert len(db.scalars(select(RiverStatusLog)).all()) == 3  # riwayat tetap lengkap


def test_stale_condition_is_flagged_not_current(client, login, ids, db):
    _cond(client, login, ids, "meluap")
    db.expire_all()
    log = db.scalars(select(RiverStatusLog)).first()
    log.created_at = utcnow() - timedelta(hours=settings.condition_stale_hours + 1)
    db.commit()
    hulu = {s["name"]: s for s in client.get("/stations", headers=login("warga1")).json()}["Pos Pantau Hulu"]
    assert hulu["condition"]["status"] == "meluap" and hulu["condition"]["stale"] is True  # "belum diperbarui"


def test_simulation_condition_is_labeled(client, login, ids, db):
    _cond(client, login, ids, "waspada", source_mode="simulation")
    db.expire_all()
    assert db.scalar(select(Alert).where(Alert.kind == AlertKind.KONDISI)).message.startswith("[SIMULASI]")


def test_hulu_condition_counts_as_upstream_alarm_for_flood_escalation(client, login, report, ids):
    body = {"region_id": ids["Kelurahan Demo"], "is_active": True, "description": "Hujan lebat", "source_mode": "real"}
    assert client.put("/weather", json=body, headers=login("pospantau1")).status_code == 200
    iid = report("warga1", at=HILIR)["incident_id"]  # jauh dari pos hulu
    report("warga2", at=HILIR_2)
    report("warga3", at=HILIR_3)
    level = lambda: client.get(f"/incidents/{iid}", headers=login("pospantau1")).json()["level"]  # noqa: E731
    assert level() != "siaga"  # 3 pelapor + cuaca, tetapi belum ada bukti hulu
    _cond(client, login, ids, "meluap")  # pos hulu menetapkan Meluap
    assert level() == "siaga"


# ---------- pengumuman ----------
def _announce(client, login, ids, user="pospantau1", expect=201, **kw):
    body = {"severity": "waspada", "region_id": ids["Kelurahan Demo"], "summary": "Sungai naik, warga bantaran waspada",
            "basis_note": "Air setinggi lutut di jembatan hulu", **kw}
    r = client.post("/announcements", json=body, headers=login(user))
    assert r.status_code == expect, r.text
    return r.json()


def test_announcement_reaches_all_roles_except_admin_on_all_channels(client, login, ids, db, set_chat, set_phone):
    _contacts(set_chat, set_phone, ALL + (("admin", 9),))
    a = _announce(client, login, ids)
    assert a["kind"] == "pengumuman" and a["sms"] is True and a["internal"] is False and a["severity"] == "waspada"
    assert "PENGUMUMAN POS PANTAU: WASPADA" in a["message"] and "BUKAN perintah evakuasi resmi" in a["message"]
    assert "pengamatan langsung" in a["message"]
    assert _deliveries(db, "telegram") == {"1001", "1003", "1004", "1005", "1006"}
    assert _deliveries(db, "sms") == {f"+62811000{n}" for n in (1, 3, 4, 5, 6)}
    assert [x["id"] for x in client.get("/alerts", headers=login("warga1")).json()] == [a["id"]]
    assert client.get("/alerts", headers=login("admin")).json() == []  # admin tidak melihat pengumuman
    assert len(notifier.sms_text(a["message"])) <= notifier.SMS_MAX_CHARS


def test_announcement_needs_a_basis_and_verified_report(client, login, report, ids):
    base = {"severity": "meluap", "region_id": ids["Kelurahan Demo"], "summary": "Sungai meluap di hulu"}
    h = login("pospantau1")
    assert client.post("/announcements", json=base, headers=h).status_code == 422  # tanpa dasar
    assert client.post("/announcements", json={**base, "basis_note": "x" * 301}, headers=h).status_code == 422
    assert client.post("/announcements", json={**base, "severity": "bencana", "basis_note": "ok"}, headers=h).status_code == 422
    assert client.post("/announcements", json={**base, "region_id": 9999, "basis_note": "ok"}, headers=h).status_code == 422
    rid = report("warga1")["id"]
    assert client.post("/announcements", json={**base, "report_id": rid}, headers=h).status_code == 422  # belum diverifikasi
    assert client.post("/announcements", json={**base, "report_id": 9999}, headers=h).status_code == 404
    assert client.post(f"/reports/{rid}/verify", json={"note": "Cocok dengan data sungai"}, headers=h).status_code == 200
    ok = client.post("/announcements", json={**base, "report_id": rid}, headers=h)
    assert ok.status_code == 201 and f"laporan warga terverifikasi #{rid}" in ok.json()["message"]


def test_announcement_correction_reaches_previous_recipients_with_reason(client, login, ids, db, set_chat, set_phone):
    _contacts(set_chat, set_phone)
    a = _announce(client, login, ids)
    set_chat("warga3", None)  # tidak lagi terdaftar, tetapi sudah menerima pengumuman awal
    set_phone("warga3", None)
    r = client.post(f"/announcements/{a['id']}/correct", json={"reason": "Ternyata genangan lokal, sudah surut"},
                    headers=login("pospantau1"))
    assert r.status_code == 201
    c = r.json()
    assert c["kind"] == "koreksi" and c["parent_id"] == a["id"] and "Ternyata genangan lokal" in c["message"]
    db.expire_all()
    for channel, expected in (("telegram", "1003"), ("sms", "+628110003")):
        got = {d.recipient for d in db.scalars(select(AlertDelivery).where(AlertDelivery.alert_id == c["id"],
                                                                           AlertDelivery.channel == channel))}
        assert expected in got  # pesan koreksi tidak diam-diam menghilang dari penerima awal
    assert db.get(Alert, a["id"]).message == a["message"]  # riwayat pengumuman tetap utuh
    assert client.post("/announcements/999/correct", json={"reason": "salah"}, headers=login("pospantau1")).status_code == 404
    assert client.post(f"/announcements/{a['id']}/correct", json={"reason": "x"}, headers=login("pospantau1")).status_code == 422


# ---------- adaptor SMS ----------
def test_sms_adapter_modes_and_failure_isolation(monkeypatch):
    assert notifier.send_sms("+62811", "tes")[0] == DeliveryStatus.MOCK
    monkeypatch.setattr(settings, "sms_mode", "live")
    st, err = notifier.send_sms("+62811", "tes")
    assert st == DeliveryStatus.GAGAL and "kosong" in err
    monkeypatch.setattr(settings, "sms_api_url", "https://sms.example/send")
    monkeypatch.setattr(settings, "sms_api_key", "rahasia-kunci")
    calls = []

    class Resp:
        status_code = 200

    def fake_post(url, **kw):
        calls.append((url, kw))
        return Resp()

    monkeypatch.setattr(notifier.httpx, "post", fake_post)
    assert notifier.send_sms("+62811", "teks")[0] == DeliveryStatus.TERKIRIM
    sent = calls[0][1]
    assert sent["json"]["to"] == "+62811" and sent["headers"]["Authorization"] == "Bearer rahasia-kunci"
    Resp.status_code = 500
    assert notifier.send_sms("+62811", "teks") == (DeliveryStatus.GAGAL, "HTTP 500")

    def boom(url, **kw):
        raise httpx.ConnectError("jaringan putus ke https://sms.example/send")

    monkeypatch.setattr(notifier.httpx, "post", boom)
    st, err = notifier.send_sms("+62811", "teks")
    assert st == DeliveryStatus.GAGAL and err == "ConnectError" and "rahasia" not in err and "example" not in err


def test_one_broken_channel_does_not_stop_the_others(client, login, ids, db, set_chat, set_phone, monkeypatch):
    set_chat("warga1", "1001")
    set_phone("warga1", "+628110001")

    def broken(phone, text):
        raise RuntimeError("gateway mati")

    monkeypatch.setattr(notifier, "send_sms", broken)
    _announce(client, login, ids)
    db.expire_all()
    rows = {(d.channel, d.recipient): d for d in db.scalars(select(AlertDelivery))}
    assert rows[("telegram", "1001")].status == DeliveryStatus.MOCK  # Telegram tetap terkirim
    assert rows[("sms", "+628110001")].status == DeliveryStatus.GAGAL and rows[("sms", "+628110001")].error == "RuntimeError"


def test_sms_text_is_short_and_has_no_footer():
    long = "[RIKSA WARGA — TES]\n" + "baris panjang " * 60 + "\nIkuti arahan koordinator dan petugas berwenang (BPBD/SAR). Darurat: 112."
    out = notifier.sms_text(long)
    assert len(out) <= notifier.SMS_MAX_CHARS and out.startswith("[RIKSA WARGA") and "Darurat: 112" not in out


# ---------- buletin pengumuman (overview live + peringatan dini) ----------
def test_bulletin_overview_and_early_warning(client, login, ids):
    obs = lambda name, cm: client.post(f"/stations/{ids[name]}/observations", json={"level_cm": cm},  # noqa: E731
                                       headers=login("pospantau1"))
    obs("Pos Pantau Hulu", 270)  # hulu meluap (bahaya 250)
    obs("Pos Pantau Hilir", 90)  # hilir normal, sungai sama
    b = client.get("/announcements/bulletin", headers=login("pospantau1")).json()
    assert b["severity"] == "meluap" and b["counts"]["meluap"] == 1
    st = {s["name"]: s for s in b["stations"]}
    assert st["Pos Pantau Hulu"]["status"] == "meluap" and st["Pos Pantau Hilir"]["status"] == "normal"
    assert any("banjir kiriman" in w for w in st["Pos Pantau Hilir"]["warnings"])  # hulu -> hilir
    assert "BULETIN KONDISI SUNGAI: SUNGAI MELUAP" in b["message"] and "PERINGATAN DINI" in b["message"]
    assert "🔴 Hulu" in b["message"] and "270 cm" in b["message"]
    assert client.get("/announcements/bulletin", headers=login("warga1")).status_code == 403


def test_bulletin_send_goes_to_telegram(client, login, ids, db):
    from app.models import Alert, AlertKind
    r = client.post("/announcements/bulletin", json={"note": "Jembatan ditutup"}, headers=login("pospantau1"))
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["kind"] == "pengumuman" and a["severity"] == "informasi"  # semua pos tanpa data/normal
    assert "Catatan pos pantau: Jembatan ditutup" in a["message"]
    db.expire_all()
    assert db.get(Alert, a["id"]).kind == AlertKind.PENGUMUMAN
    assert client.post("/announcements/bulletin", json={}, headers=login("warga1")).status_code == 403
