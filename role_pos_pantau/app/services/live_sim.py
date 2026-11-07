"""Simulator tinggi muka air (TMA) langsung untuk SEMUA pos pantau (demo; sensor fisik belum terpasang).

Setiap tick (LIVE_SIM_SECONDS, default 3 detik) tiap pos mendapat satu pembacaan baru berlabel SIMULATION.
Nilai bergerak acak di dalam "pita" sesuai kondisi sungai yang ditetapkan pos pantau:
  normal  -> di bawah ambang waspada
  waspada -> antara ambang waspada dan bahaya
  meluap  -> di atas ambang bahaya
Tombol kondisi pos pantau menggeser pita (dan langsung menambah satu bacaan di pita baru), jadi data, status, dan
notifikasi di semua role ikut berubah. Mesin aturan memproses bacaan seperti data lain (alert risiko internal bila
melewati ambang). Data simulasi tidak pernah dipakai untuk kejadian nyata (mode REAL dipisah oleh engine)."""
import random
from datetime import datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Alert, Observation, RiverCondition, RiverLevel, Role, SourceMode, Station, User
from app.services import engine
from app.services.disaster import latest_condition

HISTORY_HOURS = 12
HISTORY_STEP = timedelta(minutes=5)
KEEP = timedelta(hours=13)  # bacaan simulasi lebih lama dari ini dihapus (riwayat 12 jam cukup)
NOTES = {
    "normal": "Kondisi air sungai normal dalam batas aman",
    "waspada": "Tinggi air melewati batas waspada, pantau terus",
    "meluap": "Air melewati batas bahaya / meluap",
}
_rng = random.Random()


def band(station: Station, status: str) -> tuple[float, float]:
    w, d = station.warning_cm, station.danger_cm
    if status == RiverLevel.MELUAP.value:
        return d, d * 1.12
    if status == RiverLevel.WASPADA.value:
        return w, w + (d - w) * 0.8
    return w * 0.4, w * 0.62


def level_label(station: Station, level: float) -> str:
    if level >= station.danger_cm:
        return "meluap"
    if level >= station.warning_cm:
        return "waspada"
    return "normal"


def next_level(prev: float | None, lo: float, hi: float, rng: random.Random = _rng) -> float:
    """Bergerak menuju pita bila di luar pita; acak kecil bila di dalam pita."""
    if prev is None:
        return round((lo + hi) / 2, 1)
    if prev < lo:
        return round(min(hi, prev + max(2.0, (lo - prev) * 0.35)), 1)
    if prev > hi:
        return round(max(lo, prev - max(2.0, (prev - hi) * 0.35)), 1)
    return round(min(hi, max(lo, prev + rng.uniform(-1.5, 1.5))), 1)


def _condition(level_status: str) -> RiverCondition:
    return {"meluap": RiverCondition.MELUAP, "waspada": RiverCondition.ARUS_DERAS}.get(level_status, RiverCondition.NORMAL)


def _target(db: Session, station: Station, now: datetime) -> str:
    cond = latest_condition(db, station.id, now)
    return cond["status"].value if cond and not cond["stale"] else RiverLevel.NORMAL.value


def _system_user(db: Session) -> int | None:
    return db.scalar(select(User.id).where(User.role == Role.ADMIN).order_by(User.id))


def _add(db: Session, station: Station, level: float, at: datetime, actor: int) -> Observation:
    label = level_label(station, level)
    obs = Observation(station_id=station.id, level_cm=level, river_condition=_condition(label), note=NOTES[label],
                      source_mode=SourceMode.SIMULATION, observed_at=at, received_at=at, reported_by=actor)
    db.add(obs)
    db.flush()
    return obs


def _last(db: Session, station_id: int) -> Observation | None:
    return db.scalars(select(Observation).where(Observation.station_id == station_id)
                      .order_by(Observation.observed_at.desc(), Observation.id.desc()).limit(1)).first()


def seed_history(db: Session, now: datetime, rng: random.Random = _rng) -> int:
    """Isi riwayat 12 jam (tiap 5 menit) untuk pos yang belum punya bacaan baru, agar grafik langsung terisi."""
    actor = _system_user(db)
    if actor is None:
        return 0
    n = 0
    for st in db.scalars(select(Station)):
        last = _last(db, st.id)
        if last is not None and now - last.observed_at < timedelta(hours=1):
            continue
        lo, hi = band(st, _target(db, st, now))
        level = rng.uniform(lo, hi)
        t = now - timedelta(hours=HISTORY_HOURS)
        while t < now:
            level = next_level(level, lo, hi, rng)
            _add(db, st, level, t, actor)
            t += HISTORY_STEP
            n += 1
    return n


def tick(db: Session, now: datetime, rng: random.Random = _rng) -> list[Alert]:
    """Satu bacaan baru per pos. Pemanggil memegang engine.LOCK dan commit."""
    actor = _system_user(db)
    if actor is None:
        return []
    alerts: list[Alert] = []
    for st in db.scalars(select(Station).order_by(Station.id)):
        lo, hi = band(st, _target(db, st, now))
        last = _last(db, st.id)
        obs = _add(db, st, next_level(last.level_cm if last else None, lo, hi, rng), now, actor)
        alerts += engine.process_observation(db, st, obs, now)
    return alerts


def nudge(db: Session, station: Station, status: str, actor_id: int, now: datetime,
          rng: random.Random = _rng) -> list[Alert]:
    """Tombol kondisi pos pantau: data langsung pindah ke pita kondisi baru (bukan menunggu tick berikutnya)."""
    lo, hi = band(station, status)
    obs = _add(db, station, round(rng.uniform(lo, hi), 1), now, actor_id)
    return engine.process_observation(db, station, obs, now)


def prune(db: Session, now: datetime) -> int:
    return db.execute(delete(Observation).where(Observation.source_mode == SourceMode.SIMULATION,
                                                Observation.observed_at < now - KEEP)).rowcount or 0


def run_once(db: Session, now: datetime) -> list[Alert]:
    with engine.LOCK:
        alerts = tick(db, now)
        if now.second < 5:  # sekitar sekali per menit cukup untuk membersihkan riwayat lama
            prune(db, now)
        db.commit()
    return alerts
