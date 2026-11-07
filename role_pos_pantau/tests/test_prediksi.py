"""PRD v2 §7.1: kondisi alam dinamis, prakiraan hujan, prediksi risiko banjir, dan pencocokan laporan."""
from datetime import timedelta

import pytest
from sqlalchemy import select

from app.db import utcnow
from app.models import Alert, AlertKind, ForecastSlot, Region, Report, RiverStatusLog
from app.services import nature, notifier
from conftest import HULU, aware


@pytest.fixture
def kel(db):
    return db.scalar(select(Region).where(Region.name == "Kelurahan Demo"))


def rain(db, kel, **by_hour):
    """rain(db, kel, h0=12, h3=25) -> slot prakiraan pada +0 jam dan +3 jam dari jam bulat sekarang."""
    base = utcnow().replace(minute=0, second=0, microsecond=0)
    for key, mm in by_hour.items():
        db.add(ForecastSlot(region_id=kel.id, slot_start=base + timedelta(hours=int(key[1:])), rain_mm=mm,
                            source="BMKG prakiraan-cuaca"))
    db.commit()


def cond(client, login, ids, status, mode="real", station="Pos Pantau Hulu"):
    r = client.post(f"/stations/{ids[station]}/condition", json={"status": status, "source_mode": mode},
                    headers=login("pospantau1"))
    assert r.status_code == 201, r.text


def area(client, login, user="warga1"):
    r = client.get("/nature", headers=login(user))
    assert r.status_code == 200, r.text
    return r.json()["areas"][0]


def observe(client, login, ids, level, hours_ago):
    r = client.post(f"/stations/{ids['Pos Pantau Hulu']}/observations",
                    json={"level_cm": level, "observed_at": aware(utcnow() - timedelta(hours=hours_ago))},
                    headers=login("pospantau1"))
    assert r.status_code == 201, r.text


def test_overview_shape_and_no_data_is_honest(client, login):
    r = client.get("/nature", headers=login("warga1")).json()
    names = {s["name"] for s in r["stations"]}  # sungai berbagai daerah
    assert {"Pos Pantau Hulu", "Pos Pantau Hilir", "Pos Pantau Cikapundung Gandok", "Pos Pantau Retensi Gedebage"} <= names
    assert len(names) == 7
    a = r["areas"][0]
    assert a["level"] == "rendah" and a["confidence"] == "rendah" and a["reasons"][0].startswith("Data belum cukup")
    assert "bukan kepastian" in r["note"]


def test_rain_forecast_drives_risk_and_is_labeled_forecast(client, login, db, kel):
    rain(db, kel, h0=12, h3=25)  # 37 mm dalam 6 jam
    a = area(client, login)
    assert a["level"] == "sedang" and any("lebat" in x for x in a["reasons"])
    assert a["confidence"] == "sedang" and a["inputs"] == ["hujan"]  # baru satu jenis data
    assert [f["label"] for f in a["forecast"]] == ["prakiraan", "prakiraan"]


def test_river_condition_raises_risk_and_confidence(client, login, ids, db, kel):
    rain(db, kel, h0=12, h3=25)
    cond(client, login, ids, "waspada")
    assert area(client, login)["level"] == "sedang"  # 3 + 2
    cond(client, login, ids, "meluap")
    a = area(client, login)
    assert a["level"] == "tinggi" and a["confidence"] == "tinggi" and a["simulation"] is False
    assert any("MELUAP" in x for x in a["reasons"])


def test_stale_condition_is_not_used_as_current(client, login, ids, db, kel):
    rain(db, kel, h0=12, h3=25)
    cond(client, login, ids, "meluap")
    db.expire_all()
    db.scalars(select(RiverStatusLog)).first().created_at = utcnow() - timedelta(hours=7)
    db.commit()
    a = area(client, login)
    assert a["level"] == "sedang" and not any("MELUAP" in x for x in a["reasons"])  # kembali hanya dari hujan


def test_trend_and_eta_to_warning_threshold(client, login, ids):
    for level, hours_ago in ((60, 2), (80, 1), (100, 0)):  # naik 20 cm/jam; ambang waspada hulu 150 cm
        observe(client, login, ids, level, hours_ago)
    r = client.get("/nature", headers=login("sar1")).json()
    hulu = next(s for s in r["stations"] if s["name"] == "Pos Pantau Hulu")
    assert hulu["trend"] == "naik" and hulu["rate_cm_per_hour"] == 20.0 and hulu["eta_to_warning_hours"] == 2.5
    a = r["areas"][0]
    assert a["level"] == "sedang" and any("~2.5 jam" in x for x in a["reasons"])
    assert a["inputs"] == ["tinggi_air"]


def test_old_observation_is_not_shown_as_current_level(client, login, ids):
    observe(client, login, ids, 140, 2)  # 2 jam lalu: kedaluwarsa (batas 30 menit)
    hulu = next(s for s in client.get("/nature", headers=login("warga1")).json()["stations"] if s["name"] == "Pos Pantau Hulu")
    assert hulu["level_cm"] is None and hulu["level_status"] == "data_kedaluwarsa" and hulu["eta_to_warning_hours"] is None


def test_simulation_input_is_flagged(client, login, ids):
    cond(client, login, ids, "waspada", mode="simulation")
    assert area(client, login)["simulation"] is True


def test_risk_rise_notifies_once_and_sms_only_for_high(client, login, ids, db, kel, set_chat, set_phone):
    set_chat("warga1", "1001")
    set_phone("warga1", "+628110001")
    rain(db, kel, h0=12, h3=25)
    fired = nature.prediction_tick(db, utcnow())
    db.commit()
    assert [(a.kind, a.severity, a.sms) for a in fired] == [(AlertKind.PREDIKSI, "sedang", False)]
    assert "PERKIRAAN" in fired[0].message and "bukan kepastian" in fired[0].message
    assert nature.prediction_tick(db, utcnow()) == []  # risiko sama: tidak mengirim ulang
    cond(client, login, ids, "meluap")
    db.expire_all()
    fired = nature.prediction_tick(db, utcnow())
    db.commit()
    assert [(a.severity, a.sms) for a in fired] == [("tinggi", True)]  # SMS hanya untuk Tinggi
    notifier.deliver(db.get_bind(), [a.id for a in fired])
    db.expire_all()
    from app.models import AlertDelivery
    assert {(d.channel, d.recipient) for d in db.scalars(select(AlertDelivery))} == {("telegram", "1001"), ("sms", "+628110001")}
    assert nature.prediction_tick(db, utcnow()) == []
    assert len(db.scalars(select(Alert).where(Alert.kind == AlertKind.PREDIKSI)).all()) == 2


# ---------- pencocokan laporan (FR-025) ----------
def match(client, login, rid):
    r = client.get(f"/reports/{rid}/match", headers=login("pospantau1"))
    assert r.status_code == 200, r.text
    return r.json()


def test_report_match_verdicts(client, login, report, ids, db, kel):
    rid = report("warga1", at=HULU)["id"]
    m = match(client, login, rid)
    assert m["hasil"] == "data_kurang" and "alat bantu" in m["catatan"]  # belum ada data sungai/hujan
    base = utcnow() - timedelta(minutes=30)  # titik waktu prakiraan terdekat (+/- 1,5 jam)
    db.add(ForecastSlot(region_id=kel.id, slot_start=base, rain_mm=12, source="BMKG prakiraan-cuaca"))
    db.commit()
    cond(client, login, ids, "waspada")
    m = match(client, login, rid)
    assert m["hasil"] == "sesuai"
    assert {c["pemeriksaan"]: c["hasil"] for c in m["pemeriksaan"]}["sungai"] == "ok"
    db.expire_all()
    db.scalars(select(ForecastSlot)).first().rain_mm = 0  # hujan tidak mendukung
    db.commit()
    assert match(client, login, rid)["hasil"] == "sesuai"  # data pos naik cukup; hujan hanya pendukung
    cond(client, login, ids, "normal")
    assert match(client, login, rid)["hasil"] == "tidak_sesuai"
    # laporan tetap tersimpan walau tidak sesuai (FR-027)
    assert client.get(f"/reports/{rid}", headers=login("pospantau1")).status_code == 200


def test_report_with_station_area_matches_that_station(client, login, report, ids, db):
    sid = ids["Pos Pantau Hilir"]
    r = report("warga1", at=HULU, region_id=None, station_id=sid)  # area dipilih, pin boleh di titik lain
    assert r["station_id"] == sid and r["station_name"] == "Pos Pantau Hilir"
    assert db.get(Report, r["id"]).region_id == ids["RT 01 / RW 02"]  # wilayah kejadian = wilayah pos
    sungai = {c["pemeriksaan"]: c for c in match(client, login, r["id"])["pemeriksaan"]}["sungai"]
    assert sungai["keterangan"].startswith("Pos Pantau Hilir") and "area dipilih pelapor" in sungai["keterangan"]
    report("warga1", region_id=None, expect=422)  # area pos atau wilayah wajib
    report("warga1", region_id=None, station_id=9999, expect=422)


def test_reported_water_condition_is_compared_with_station(client, login, report, ids, db, kel):
    sid = ids["Pos Pantau Hulu"]
    up = report("warga1", region_id=None, station_id=sid, water_condition="meluap")["id"]
    calm = report("warga2", region_id=None, station_id=sid, water_condition="normal")["id"]
    cond(client, login, ids, "meluap")  # tanpa hujan sama sekali
    m = match(client, login, up)
    assert m["hasil"] == "sesuai" and m["banjir"] is True
    m = match(client, login, calm)  # pos meluap tapi pelapor bilang normal
    assert m["hasil"] == "tidak_sesuai"  # tidak sejalan, tanpa data hujan pendukung
    assert {c["pemeriksaan"]: c["hasil"] for c in m["pemeriksaan"]}["sungai"] == "tidak"
    cond(client, login, ids, "normal")
    assert match(client, login, up)["hasil"] == "tidak_sesuai"


def test_live_rain_supports_match(client, login, report, monkeypatch):
    from app.services import weather_live
    sample = {"current": {"time": "2026-11-07T14:15", "temperature_2m": 24, "relative_humidity_2m": 90,
                          "precipitation": 6.0, "rain": 6.0, "weather_code": 63, "wind_speed_10m": 3}}
    monkeypatch.setattr(weather_live, "http_get", lambda params: sample)
    weather_live.current(force=True)
    rid = report("warga1", at=HULU)["id"]
    hujan = {c["pemeriksaan"]: c for c in match(client, login, rid)["pemeriksaan"]}["hujan"]
    assert hujan["hasil"] == "ok" and "Open-Meteo saat ini 6 mm/jam" in hujan["keterangan"]


def test_match_uses_live_level_without_condition_button(client, login, report, ids):
    sid = ids["Pos Pantau Hulu"]  # waspada 150, bahaya 250; kondisi pos tidak pernah diatur
    calm = report("warga1", region_id=None, station_id=sid, water_condition="normal")["id"]
    up = report("warga2", region_id=None, station_id=sid, water_condition="meluap")["id"]
    client.post(f"/stations/{sid}/observations", json={"level_cm": 80}, headers=login("pospantau1"))
    m = match(client, login, calm)
    assert m["hasil"] == "sesuai" and m["banjir"] is False  # laporan normal & angka normal = cocok
    assert "tinggi air 80 cm = normal" in m["pemeriksaan"][0]["keterangan"]
    assert match(client, login, up)["hasil"] == "tidak_sesuai"
    client.post(f"/stations/{sid}/observations", json={"level_cm": 270}, headers=login("pospantau1"))
    m = match(client, login, up)
    assert m["hasil"] == "sesuai" and m["banjir"] is True
    assert "270 cm = meluap" in m["pemeriksaan"][0]["keterangan"]
