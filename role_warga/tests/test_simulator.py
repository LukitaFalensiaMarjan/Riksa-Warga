"""Simulator tinggi air (FR-012): berlabel SIMULATION, memicu mesin aturan, terpisah dari data nyata."""
import pytest
from sqlalchemy import select

from app.models import Alert, Observation, SourceMode


@pytest.fixture
def hulu(ids):
    return ids["Pos Pantau Hulu"]  # ambang waspada 150 cm, bahaya 250 cm


def step(client, login, sid, user="koord_rw01", scenario=None):
    body = None if scenario is None else {"scenario": scenario}
    return client.post(f"/simulation/stations/{sid}/step", json=body, headers=login(user))


def test_steps_rise_and_are_labeled_simulation(client, login, hulu, db):
    levels = []
    for _ in range(4):
        r = step(client, login, hulu)
        assert r.status_code == 201 and r.json()["source_mode"] == "simulation" and r.json()["note"] == "SIMULASI"
        levels.append(r.json()["level_cm"])
    assert levels == [40.0, 58.0, 76.0, 94.0]  # mulai 40 cm, +12% ambang waspada per langkah
    db.expire_all()
    assert {o.source_mode for o in db.scalars(select(Observation))} == {SourceMode.SIMULATION}
    trend = client.get(f"/stations/{hulu}/trend", headers=login("koord_rw01")).json()
    assert trend["direction"] == "naik"


def test_crossing_thresholds_triggers_internal_risk_alert(client, login, hulu, db):
    for _ in range(7):  # 40 ... 148 cm, belum melewati 150
        step(client, login, hulu)
    risk = lambda: [a for a in client.get("/alerts", headers=login("koord_rw01")).json() if a["kind"] == "risiko"]  # noqa: E731
    assert risk() == []
    step(client, login, hulu)  # 166 cm
    alerts = risk()
    assert len(alerts) == 1 and "SIMULASI" in alerts[0]["message"]
    db.expire_all()
    assert all(a.internal for a in db.scalars(select(Alert).where(Alert.station_id == hulu)))  # internal, bukan publik


def test_scenarios_are_bounded(client, login, hulu):
    top = [step(client, login, hulu).json()["level_cm"] for _ in range(40)]
    assert max(top) == 250 * 1.3  # tidak naik tanpa batas
    down = [step(client, login, hulu, scenario="turun").json()["level_cm"] for _ in range(40)]
    assert down[-1] == 0.0 and min(down) >= 0.0  # tidak negatif


def test_simulation_never_changes_real_incident(client, login, hulu, report):
    rid = report("warga1")["id"]  # laporan nyata dekat pos hulu
    for _ in range(14):  # melewati ambang bahaya (simulasi)
        step(client, login, hulu)
    detail = client.get(f"/reports/{rid}", headers=login("pospantau1")).json()
    assert "pos_pantau_ambang" not in {f["faktor"] for f in detail["score_factors"]}


def test_access_rules(client, login, hulu, ids):
    assert step(client, login, 9999).status_code == 404
    assert step(client, login, hulu, user="pospantau1").status_code == 201
    assert step(client, login, hulu, user="koord_rw02").status_code == 403  # pos di luar wilayah RW 02
    for user in ("warga1", "sar1", "admin"):
        assert step(client, login, hulu, user=user).status_code == 403
    assert client.post(f"/simulation/stations/{hulu}/step", json={"scenario": "banjir_bandang"},
                       headers=login("pospantau1")).status_code == 422
