"""Mesin aturan: skor laporan, pengelompokan jadi kejadian, eskalasi level, dan perubahan manual.

Batas keselamatan (PRD §9):
- Otomatis maksimal SIAGA. EVAKUASI hanya lewat set_level_manual oleh manusia.
- Engine tidak pernah menurunkan level atau menghapus laporan.
- Laporan duplikat/ditolak/bertanda pemeriksaan tidak dihitung sebagai pelapor unik.
- Data simulasi tidak pernah bercampur dengan kejadian nyata (FR-012).
"""
import functools
import threading
from datetime import datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import log_action
from app.auth import ancestor_at_level, area_scope_ids, region_ancestor_ids
from app.models import (
    Alert,
    AlertKind,
    AlertLevel,
    Hazard,
    Incident,
    IncidentStatus,
    Observation,
    Report,
    ReportSource,
    ReportStatus,
    SourceMode,
    Station,
    User,
    Verification,
    WeatherContext,
)
from app.services import messages
from app.services.geo import haversine_m
from app.services.rules import RuleParams, get_rules

LEVEL_ORDER = {AlertLevel.PANTAU: 1, AlertLevel.WASPADA: 2, AlertLevel.SIAGA: 3, AlertLevel.EVAKUASI: 4}
REVIEW_FLAGS = {"foto_pernah_dipakai", "lokasi_tidak_cocok", "waktu_laporan_lama"}
FLAG_NOTES = {
    "foto_pernah_dipakai": "Foto identik dengan laporan lain",
    "lokasi_tidak_cocok": "GPS perangkat jauh dari pin lokasi",
    "waktu_laporan_lama": "Waktu kejadian jauh sebelum laporan dikirim",
}
STALE_REPORT = timedelta(hours=6)
GPS_MISMATCH_M = 1000

# shortcut: kunci per proses, aman hanya untuk 1 proses uvicorn; banyak worker -> ganti GET_LOCK MySQL / row lock
LOCK = threading.Lock()


def locked(fn):
    """Endpoint yang mengubah kejadian dijalankan satu per satu: cegah kejadian kembar dan alert ganda
    (threadpool FastAPI + loop tick berjalan paralel). Background task Telegram berjalan di luar kunci."""
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with LOCK:
            return fn(*args, **kwargs)
    return wrapper


# ---------- helper ----------

def counts_as_reporter(r: Report) -> bool:
    if r.status == ReportStatus.TERVERIFIKASI:
        return True
    return r.status == ReportStatus.DITERIMA and not (set(r.flags or []) & REVIEW_FLAGS)


def _mode(incident: Incident) -> SourceMode:
    return SourceMode.SIMULATION if incident.is_simulation else SourceMode.REAL


def weather_active(db: Session, region_id: int, now: datetime, mode: SourceMode) -> bool:
    rows = db.scalars(select(WeatherContext).where(
        WeatherContext.region_id.in_(region_ancestor_ids(db, region_id)), WeatherContext.is_active.is_(True),
        WeatherContext.source_mode == mode)).all()
    return any(w.valid_until is None or w.valid_until > now for w in rows)


def upstream_station_alarm(db: Session, region_id: int, rules: RuleParams, now: datetime,
                           mode: SourceMode) -> bool:
    stations = db.scalars(select(Station).where(
        Station.is_upstream.is_(True), Station.region_id.in_(area_scope_ids(db, region_id)))).all()
    since = now - timedelta(minutes=rules.window_minutes)
    for s in stations:
        obs = db.scalars(select(Observation).where(Observation.station_id == s.id, Observation.source_mode == mode)
                         .order_by(Observation.observed_at.desc(), Observation.id.desc()).limit(1)).first()
        if obs and obs.observed_at >= since and obs.level_cm >= s.warning_cm:
            return True
    return False


def _near_upstream_station(db: Session, lat: float, lng: float, radius_m: float) -> bool:
    stations = db.scalars(select(Station).where(Station.is_upstream.is_(True))).all()
    return any(haversine_m(lat, lng, s.lat, s.lng) <= radius_m for s in stations)


def _public_audience(db: Session, incident: Incident) -> int:
    rules = get_rules(db, incident.hazard)
    return ancestor_at_level(db, incident.region_id, rules.audience_level) or incident.region_id


def _add_alert(db: Session, incident: Incident | None, kind: AlertKind, text: str, *, internal: bool,
               audience_region_id: int, now: datetime, actor_id: int | None = None,
               reason: str | None = None, station_id: int | None = None) -> Alert:
    alert = Alert(
        incident_id=incident.id if incident else None, station_id=station_id, kind=kind,
        level=incident.level if incident else None,
        verification=incident.verification if incident else None,
        audience_region_id=audience_region_id, internal=internal, message=text, reason=reason,
        created_by=actor_id, created_at=now,
    )
    db.add(alert)
    db.flush()
    return alert


def _had_public_alert(db: Session, incident: Incident) -> bool:
    return db.scalar(select(func.count(Alert.id)).where(
        Alert.incident_id == incident.id, Alert.internal.is_(False))) > 0


# ---------- skor ----------

def score_report(db: Session, r: Report, *, unique: int, station_alarm: bool, weather: bool,
                 rules: RuleParams) -> tuple[int, list[dict]]:
    w = rules.weights
    flags = set(r.flags or [])
    factors: list[dict] = []

    def add(name: str, points: int, note: str) -> None:
        factors.append({"faktor": name, "poin": points, "keterangan": note})

    add("dasar", w["dasar"], "Laporan diterima dan disimpan")
    if r.status == ReportStatus.DUPLIKAT:
        add("duplikat", 0, f"Duplikat dari laporan #{r.duplicate_of}; tidak dihitung sebagai pelapor unik")
    if r.status == ReportStatus.DITOLAK:
        add("ditolak", 0, "Ditolak koordinator; tidak dihitung sebagai pelapor unik")
    if r.status == ReportStatus.TERVERIFIKASI:
        add("verifikasi_koordinator", w["verifikasi"], "Diverifikasi koordinator")
    if r.photo_path:
        if "foto_pernah_dipakai" in flags:
            add("foto", 0, "Foto identik dengan laporan lain; perlu pemeriksaan")
        else:
            add("foto", w["foto"], "Melampirkan foto (tetap perlu diperiksa manusia)")
    if unique > 1:
        add("pelapor_lain", min((unique - 1) * w["pelapor_lain"], w["pelapor_lain_maks"]),
            f"{unique} pelapor unik di kelompok kejadian ini")
    if r.hazard == Hazard.BANJIR and r.is_upstream:
        add("hulu", w["hulu"], "Lokasi dekat pos pantau hulu")
    if station_alarm:
        add("pos_pantau_ambang", w["pos_pantau_ambang"], "Pos pantau hulu di atas ambang waspada")
    if weather:
        add("cuaca", w["cuaca"], "Konteks cuaca aktif (faktor pendukung, bukan bukti)")
    if r.source != ReportSource.WARGA:
        label = f"Sumber: {r.source.value}" + (" (SIMULASI)" if r.source_mode == SourceMode.SIMULATION else "")
        add("sumber_petugas", w["sumber_petugas"], label)
    verified = db.scalar(select(func.count(Report.id)).where(
        Report.reporter_id == r.reporter_id, Report.id != r.id, Report.status == ReportStatus.TERVERIFIKASI))
    if verified:
        add("reputasi", min(verified * w["reputasi"], w["reputasi_maks"]),
            f"{verified} laporan sebelumnya terverifikasi")
    for flag in sorted(flags & (REVIEW_FLAGS - {"foto_pernah_dipakai"})):
        add(flag, 0, f"Perlu pemeriksaan: {FLAG_NOTES[flag]}")
    return sum(f["poin"] for f in factors), factors


# ---------- alur otomatis ----------

def process_new_report(db: Session, report: Report, now: datetime) -> list[Alert]:
    rules = get_rules(db, report.hazard)
    flags = []
    if report.received_at - report.reported_at > STALE_REPORT:
        flags.append("waktu_laporan_lama")
    if report.gps_lat is not None and haversine_m(
            report.lat, report.lng, report.gps_lat, report.gps_lng) > GPS_MISMATCH_M:
        flags.append("lokasi_tidak_cocok")
    report.flags = flags
    report.is_upstream = report.hazard == Hazard.BANJIR and _near_upstream_station(
        db, report.lat, report.lng, rules.upstream_radius_m)

    dup = _find_duplicate(db, report, rules, now)
    if dup is not None:
        report.status = ReportStatus.DUPLIKAT
        report.duplicate_of = dup.id
        incident = db.get(Incident, dup.incident_id)
    else:
        incident = _find_open_incident(db, report, rules, now)

    alerts: list[Alert] = []
    if incident is None:
        incident = Incident(
            hazard=report.hazard, region_id=report.region_id, lat=report.lat, lng=report.lng,
            status=IncidentStatus.AKTIF, level=AlertLevel.PANTAU, verification=Verification.BELUM,
            is_simulation=report.source_mode == SourceMode.SIMULATION,
            started_at=now, last_report_at=now, updated_at=now,
        )
        db.add(incident)
        db.flush()
        report.incident_id = incident.id
        db.flush()  # sessionmaker autoflush=False: pesan di bawah membaca laporan lewat query
        alerts.append(_add_alert(db, incident, AlertKind.PANTAU, messages.pantau_message(db, incident, now),
                                 internal=True, audience_region_id=incident.region_id, now=now))
    else:
        report.incident_id = incident.id
    incident.last_report_at = now
    db.flush()
    return alerts + evaluate_incident(db, incident, now)


def _find_duplicate(db: Session, report: Report, rules: RuleParams, now: datetime) -> Report | None:
    cands = db.scalars(select(Report).join(Incident, Report.incident_id == Incident.id).where(
        Report.reporter_id == report.reporter_id, Report.hazard == report.hazard, Report.id != report.id,
        # laporan yang ditolak bukan pembanding: bukti baru setelah penolakan harus tetap dihitung
        Report.status.not_in([ReportStatus.DUPLIKAT, ReportStatus.DITOLAK]),
        Incident.status == IncidentStatus.AKTIF,
        Incident.is_simulation == (report.source_mode == SourceMode.SIMULATION),
        Report.received_at >= now - timedelta(minutes=rules.duplicate_window_minutes),
    )).all()
    for c in cands:
        if haversine_m(c.lat, c.lng, report.lat, report.lng) <= rules.duplicate_radius_m:
            return c
    return None


def _find_open_incident(db: Session, report: Report, rules: RuleParams, now: datetime) -> Incident | None:
    cands = db.scalars(select(Incident).where(
        Incident.hazard == report.hazard, Incident.status == IncidentStatus.AKTIF,
        Incident.is_simulation == (report.source_mode == SourceMode.SIMULATION),
        Incident.last_report_at >= now - timedelta(minutes=rules.window_minutes),
    )).all()
    scored = [(haversine_m(c.lat, c.lng, report.lat, report.lng), c) for c in cands]
    scored = [t for t in scored if t[0] <= rules.radius_m]
    return min(scored, key=lambda t: t[0])[1] if scored else None


def evaluate_incident(db: Session, incident: Incident, now: datetime) -> list[Alert]:
    """Hitung ulang skor & pelapor unik, lalu naikkan level bila aturan terpenuhi."""
    if incident.status != IncidentStatus.AKTIF:
        return []
    rules = get_rules(db, incident.hazard)
    reports = db.scalars(select(Report).where(Report.incident_id == incident.id)).all()
    counted = [r for r in reports if counts_as_reporter(r)]
    unique = len({r.reporter_id for r in counted})
    is_flood = incident.hazard == Hazard.BANJIR
    # bukti pendukung (pos hulu, cuaca) hanya dari mode yang sama dengan kejadian
    station_alarm = is_flood and upstream_station_alarm(db, incident.region_id, rules, now, _mode(incident))
    upstream = station_alarm or any(r.is_upstream for r in counted)
    weather = is_flood and weather_active(db, incident.region_id, now, _mode(incident))

    incident.unique_reporters = unique
    for r in reports:
        r.score, r.score_factors = score_report(
            db, r, unique=unique, station_alarm=station_alarm, weather=weather, rules=rules)
    incident.score = max((r.score for r in reports), default=0)

    current = LEVEL_ORDER[incident.level]
    siaga_ok = (unique >= rules.siaga_min_reporters
                and (upstream or not rules.siaga_requires_upstream)
                and (weather or not rules.siaga_requires_weather))
    if siaga_ok and current < LEVEL_ORDER[AlertLevel.SIAGA]:
        parts = [f"{unique} pelapor unik"]
        if rules.siaga_requires_upstream:
            parts.append("indikasi hulu")
        if rules.siaga_requires_weather:
            parts.append("konteks cuaca aktif")
        return [_apply_level(db, incident, AlertLevel.SIAGA, actor_id=None,
                             trigger="otomatis: " + " + ".join(parts), reason=None,
                             verification=incident.verification, now=now)]

    if incident.pending_level is not None and unique < rules.waspada_min_reporters:
        # bukti berkurang (laporan ditolak/ditandai) -> usulan ditarik agar timer tidak menaikkan level
        incident.pending_level = incident.pending_since = None
        log_action(db, actor_id=None, action="incident.withdraw_proposal", entity_type="incident",
                   entity_id=incident.id, new={"unique_reporters": unique})
        return []

    if (unique >= rules.waspada_min_reporters and current < LEVEL_ORDER[AlertLevel.WASPADA]
            and incident.pending_level is None):
        incident.pending_level = AlertLevel.WASPADA
        incident.pending_since = now
        log_action(db, actor_id=None, action="incident.propose", entity_type="incident", entity_id=incident.id,
                   new={"level": AlertLevel.WASPADA.value, "unique_reporters": unique})
        text = messages.proposal_message(db, incident, rules.waspada_timeout_minutes, now)
        return [_add_alert(db, incident, AlertKind.USULAN, text, internal=True,
                           audience_region_id=incident.region_id, now=now)]
    return []


def tick(db: Session, now: datetime) -> list[Alert]:
    """Terapkan usulan Waspada yang tidak direspons koordinator sampai batas waktu."""
    alerts: list[Alert] = []
    pending = db.scalars(select(Incident).where(
        Incident.status == IncidentStatus.AKTIF, Incident.pending_level.is_not(None))).all()
    for inc in pending:
        rules = get_rules(db, inc.hazard)
        if inc.pending_since + timedelta(minutes=rules.waspada_timeout_minutes) > now:
            continue
        if LEVEL_ORDER[inc.level] < LEVEL_ORDER[inc.pending_level]:
            trigger = f"otomatis: tidak ada respons koordinator dalam {rules.waspada_timeout_minutes} menit"
            # pertahankan verifikasi manusia; kejadian baru memang mulai BELUM
            alerts.append(_apply_level(db, inc, inc.pending_level, actor_id=None, trigger=trigger, reason=None,
                                       verification=inc.verification, now=now))
        else:
            inc.pending_level = inc.pending_since = None
    return alerts


def process_observation(db: Session, station: Station, obs: Observation, now: datetime) -> list[Alert]:
    prev = db.scalars(select(Observation).where(Observation.station_id == station.id, Observation.id != obs.id)
                      .order_by(Observation.observed_at.desc(), Observation.id.desc()).limit(1)).first()
    alerts: list[Alert] = []
    is_latest = prev is None or obs.observed_at >= prev.observed_at
    if is_latest:
        for label, threshold in (("bahaya", station.danger_cm), ("waspada", station.warning_cm)):
            if obs.level_cm >= threshold and (prev is None or prev.level_cm < threshold):
                alerts.append(_add_alert(db, None, AlertKind.RISIKO,
                                         messages.risk_message(station, obs, label, threshold), internal=True,
                                         audience_region_id=station.region_id, now=now, station_id=station.id))
                break
    if station.is_upstream:
        incidents = db.scalars(select(Incident).where(
            Incident.status == IncidentStatus.AKTIF, Incident.hazard == Hazard.BANJIR,
            Incident.region_id.in_(area_scope_ids(db, station.region_id)))).all()
        for inc in incidents:
            alerts += evaluate_incident(db, inc, now)
    return alerts


def reevaluate_region(db: Session, region_ids: set[int], now: datetime) -> list[Alert]:
    incidents = db.scalars(select(Incident).where(
        Incident.status == IncidentStatus.AKTIF, Incident.region_id.in_(region_ids))).all()
    return [a for inc in incidents for a in evaluate_incident(db, inc, now)]


# ---------- perubahan level ----------

def _apply_level(db: Session, incident: Incident, new_level: AlertLevel, *, actor_id: int | None, trigger: str,
                 reason: str | None, verification: Verification, now: datetime) -> Alert:
    if actor_id is None and new_level == AlertLevel.EVAKUASI:
        raise RuntimeError("Evakuasi tidak boleh ditetapkan otomatis")
    old = incident.level
    kind = AlertKind.KOREKSI if LEVEL_ORDER[new_level] < LEVEL_ORDER[old] else AlertKind.LEVEL
    incident.level = new_level
    incident.verification = verification
    incident.pending_level = incident.pending_since = None
    incident.updated_at = now
    log_action(db, actor_id=actor_id, action="incident.level", entity_type="incident", entity_id=incident.id,
               old={"level": old.value},
               new={"level": new_level.value, "verification": verification.value, "pemicu": trigger},
               reason=reason)
    audience = _public_audience(db, incident)
    text = messages.level_message(db, incident, kind, old, audience, reason, now)
    return _add_alert(db, incident, kind, text, internal=False, audience_region_id=audience, now=now,
                      actor_id=actor_id, reason=reason)


def _require_active(incident: Incident) -> None:
    if incident.status != IncidentStatus.AKTIF:
        raise HTTPException(status.HTTP_409_CONFLICT, f"Kejadian sudah {incident.status.value}")


def set_level_manual(db: Session, incident: Incident, new_level: AlertLevel, user: User, reason: str,
                     now: datetime) -> Alert:
    _require_active(incident)
    if new_level == incident.level:
        raise HTTPException(status.HTTP_409_CONFLICT, "Level sama; gunakan /verify untuk konfirmasi")
    if new_level == AlertLevel.EVAKUASI and LEVEL_ORDER[incident.level] < LEVEL_ORDER[AlertLevel.SIAGA]:
        raise HTTPException(status.HTTP_409_CONFLICT, "Evakuasi hanya dapat ditetapkan setelah level Siaga")
    return _apply_level(db, incident, new_level, actor_id=user.id, trigger="manual koordinator", reason=reason,
                        verification=Verification.TERVERIFIKASI, now=now)


def verify_incident(db: Session, incident: Incident, user: User, note: str | None, now: datetime) -> None:
    _require_active(incident)
    old = incident.verification
    incident.verification = Verification.TERVERIFIKASI
    incident.updated_at = now
    log_action(db, actor_id=user.id, action="incident.verify", entity_type="incident", entity_id=incident.id,
               old={"verification": old.value}, new={"verification": incident.verification.value}, reason=note)


def dismiss_proposal(db: Session, incident: Incident, user: User, reason: str, now: datetime) -> None:
    _require_active(incident)
    if incident.pending_level is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tidak ada usulan level yang menunggu")
    old = incident.pending_level
    incident.pending_level = incident.pending_since = None
    incident.updated_at = now
    log_action(db, actor_id=user.id, action="incident.dismiss_proposal", entity_type="incident",
               entity_id=incident.id, old={"pending_level": old.value}, new={"pending_level": None}, reason=reason)


def _end_incident(db: Session, incident: Incident, user: User, reason: str, now: datetime,
                  new_status: IncidentStatus) -> Alert:
    _require_active(incident)
    public = _had_public_alert(db, incident)
    incident.status = new_status
    incident.pending_level = incident.pending_since = None
    incident.updated_at = now
    log_action(db, actor_id=user.id, action=f"incident.{new_status.value}", entity_type="incident",
               entity_id=incident.id, old={"status": IncidentStatus.AKTIF.value},
               new={"status": new_status.value}, reason=reason)
    audience = _public_audience(db, incident) if public else incident.region_id
    if new_status == IncidentStatus.DIBATALKAN:
        kind, text = AlertKind.PEMBATALAN, messages.cancel_message(db, incident, audience, reason, now)
    else:
        kind, text = AlertKind.SELESAI, messages.close_message(db, incident, audience, reason, now)
    # tidak pernah ada alert publik -> pembatalan cukup internal
    return _add_alert(db, incident, kind, text, internal=not public, audience_region_id=audience, now=now,
                      actor_id=user.id, reason=reason)


def cancel_incident(db: Session, incident: Incident, user: User, reason: str, now: datetime) -> Alert:
    return _end_incident(db, incident, user, reason, now, IncidentStatus.DIBATALKAN)


def close_incident(db: Session, incident: Incident, user: User, reason: str, now: datetime) -> Alert:
    return _end_incident(db, incident, user, reason, now, IncidentStatus.SELESAI)
