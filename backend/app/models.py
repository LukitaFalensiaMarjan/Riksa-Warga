from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, Boolean, DateTime, Double, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base, utcnow


def _enum(e: type[StrEnum]) -> Enum:
    # simpan value ("koordinator"), bukan nama member; native ENUM di MySQL
    return Enum(e, values_callable=lambda x: [m.value for m in x], length=32)


class Role(StrEnum):
    WARGA = "warga"
    KOORDINATOR = "koordinator"
    POS_PANTAU = "pos_pantau"
    RELAWAN = "relawan"
    PETUGAS = "petugas"
    ADMIN = "admin"


class RegionLevel(StrEnum):
    PROVINSI = "provinsi"
    KABUPATEN_KOTA = "kabupaten_kota"
    KECAMATAN = "kecamatan"
    KELURAHAN = "kelurahan"
    RW = "rw"
    RT = "rt"


class Region(Base):
    __tablename__ = "regions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("regions.id"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    level: Mapped[RegionLevel] = mapped_column(_enum(RegionLevel))

    parent: Mapped["Region | None"] = relationship(remote_side=[id])


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[Role] = mapped_column(_enum(Role))
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), index=True)
    phone: Mapped[str | None] = mapped_column(String(32))
    telegram_chat_id: Mapped[str | None] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    region: Mapped[Region] = relationship()


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(64))
    entity_type: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    old_value: Mapped[dict | None] = mapped_column(JSON)
    new_value: Mapped[dict | None] = mapped_column(JSON)
    reason: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


# ---------- Enum domain ----------

class Hazard(StrEnum):
    BANJIR = "banjir"
    KEBAKARAN = "kebakaran"


class FireIndicator(StrEnum):
    API = "api"
    ASAP = "asap"
    PANAS = "panas"
    GAS = "gas"
    LEDAKAN = "ledakan"
    LAINNYA = "lainnya"


class SourceMode(StrEnum):
    REAL = "real"
    SIMULATION = "simulation"


class ReportSource(StrEnum):
    WARGA = "warga"
    POS_PANTAU = "pos_pantau"
    SENSOR = "sensor"
    KOORDINATOR = "koordinator"


class ReportStatus(StrEnum):
    DITERIMA = "diterima"
    TERVERIFIKASI = "terverifikasi"
    DITOLAK = "ditolak"
    DUPLIKAT = "duplikat"


class RiverCondition(StrEnum):
    NORMAL = "normal"
    NAIK = "naik"
    ARUS_DERAS = "arus_deras"
    MELUAP = "meluap"


class IncidentStatus(StrEnum):
    AKTIF = "aktif"
    SELESAI = "selesai"
    DIBATALKAN = "dibatalkan"


class AlertLevel(StrEnum):
    PANTAU = "pantau"
    WASPADA = "waspada"
    SIAGA = "siaga"
    EVAKUASI = "evakuasi"


class Verification(StrEnum):
    BELUM = "belum_diverifikasi"
    TERVERIFIKASI = "terverifikasi"


class AlertKind(StrEnum):
    PANTAU = "pantau"  # internal: laporan/kejadian baru
    USULAN = "usulan"  # internal: usulan Waspada menunggu koordinator
    RISIKO = "risiko"  # internal: pos pantau lewat ambang (status risiko, bukan kejadian)
    LEVEL = "level"
    KOREKSI = "koreksi"
    PEMBATALAN = "pembatalan"
    SELESAI = "selesai"


class DeliveryStatus(StrEnum):
    TERKIRIM = "terkirim"
    GAGAL = "gagal"
    MOCK = "mock"


class SafetyStatus(StrEnum):
    BELUM_TERKONFIRMASI = "belum_terkonfirmasi"
    AMAN_MANDIRI = "aman_mandiri"
    AMAN_TERVERIFIKASI = "aman_terverifikasi"
    BUTUH_BANTUAN = "butuh_bantuan"
    DALAM_PENANGANAN = "dalam_penanganan"
    DALAM_PERJALANAN = "dalam_perjalanan"
    TIBA_DI_TITIK_AMAN = "tiba_di_titik_aman"
    TIDAK_DAPAT_DIHUBUNGI = "tidak_dapat_dihubungi"


class StatusSource(StrEnum):
    MANDIRI = "mandiri"
    KOORDINATOR = "koordinator"
    BUDDY = "buddy"
    KELUARGA = "keluarga"
    PETUGAS = "petugas"


class NeedType(StrEnum):
    EVAKUASI = "evakuasi"
    MEDIS = "medis"
    LOGISTIK = "logistik"
    LAINNYA = "lainnya"


class Vulnerability(StrEnum):
    LANSIA = "lansia"
    DISABILITAS = "disabilitas"
    ANAK = "anak"
    SAKIT = "sakit"
    HAMIL = "hamil"
    TINGGAL_SENDIRI = "tinggal_sendiri"
    LAINNYA = "lainnya"


class ShelterStatus(StrEnum):
    TERSEDIA = "tersedia"
    TERBATAS = "terbatas"
    PENUH = "penuh"
    TIDAK_DAPAT_DIGUNAKAN = "tidak_dapat_digunakan"


# ---------- Pos pantau ----------

class Station(Base):
    __tablename__ = "stations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), index=True)
    lat: Mapped[float] = mapped_column(Double)
    lng: Mapped[float] = mapped_column(Double)
    is_upstream: Mapped[bool] = mapped_column(Boolean, default=False)
    river_name: Mapped[str | None] = mapped_column(String(120))
    warning_cm: Mapped[float] = mapped_column(Double)
    danger_cm: Mapped[float] = mapped_column(Double)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Observation(Base):
    __tablename__ = "observations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    station_id: Mapped[int] = mapped_column(ForeignKey("stations.id"), index=True)
    level_cm: Mapped[float] = mapped_column(Double)
    river_condition: Mapped[RiverCondition] = mapped_column(_enum(RiverCondition))
    note: Mapped[str | None] = mapped_column(Text)
    source_mode: Mapped[SourceMode] = mapped_column(_enum(SourceMode))
    observed_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    reported_by: Mapped[int] = mapped_column(ForeignKey("users.id"))


# ---------- Kejadian & laporan ----------

class Incident(Base):
    __tablename__ = "incidents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hazard: Mapped[Hazard] = mapped_column(_enum(Hazard))
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), index=True)
    lat: Mapped[float] = mapped_column(Double)
    lng: Mapped[float] = mapped_column(Double)
    status: Mapped[IncidentStatus] = mapped_column(_enum(IncidentStatus), index=True)
    level: Mapped[AlertLevel] = mapped_column(_enum(AlertLevel))
    verification: Mapped[Verification] = mapped_column(_enum(Verification))
    pending_level: Mapped[AlertLevel | None] = mapped_column(_enum(AlertLevel))
    pending_since: Mapped[datetime | None] = mapped_column(DateTime)
    is_simulation: Mapped[bool] = mapped_column(Boolean, default=False)
    score: Mapped[int] = mapped_column(Integer, default=0)
    unique_reporters: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_report_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class Report(Base):
    __tablename__ = "reports"
    # client_ref: ID dari perangkat untuk laporan antrean offline; kirim ulang tidak membuat duplikat
    __table_args__ = (UniqueConstraint("reporter_id", "client_ref", name="uq_report_client_ref"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_ref: Mapped[str | None] = mapped_column(String(64))
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"), index=True)
    reporter_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), index=True)
    hazard: Mapped[Hazard] = mapped_column(_enum(Hazard))
    fire_indicator: Mapped[FireIndicator | None] = mapped_column(_enum(FireIndicator))
    source: Mapped[ReportSource] = mapped_column(_enum(ReportSource))
    source_mode: Mapped[SourceMode] = mapped_column(_enum(SourceMode))
    description: Mapped[str] = mapped_column(Text)
    lat: Mapped[float] = mapped_column(Double)
    lng: Mapped[float] = mapped_column(Double)
    gps_lat: Mapped[float | None] = mapped_column(Double)
    gps_lng: Mapped[float | None] = mapped_column(Double)
    reported_at: Mapped[datetime] = mapped_column(DateTime)
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    status: Mapped[ReportStatus] = mapped_column(_enum(ReportStatus))
    status_reason: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    duplicate_of: Mapped[int | None] = mapped_column(ForeignKey("reports.id"))
    is_upstream: Mapped[bool] = mapped_column(Boolean, default=False)
    photo_path: Mapped[str | None] = mapped_column(String(255))
    photo_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)
    score_factors: Mapped[list] = mapped_column(JSON, default=list)
    flags: Mapped[list] = mapped_column(JSON, default=list)

    @property
    def has_photo(self) -> bool:
        return self.photo_path is not None


# ---------- Peringatan ----------

class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"), index=True)
    station_id: Mapped[int | None] = mapped_column(ForeignKey("stations.id"))
    kind: Mapped[AlertKind] = mapped_column(_enum(AlertKind))
    level: Mapped[AlertLevel | None] = mapped_column(_enum(AlertLevel))
    verification: Mapped[Verification | None] = mapped_column(_enum(Verification))
    audience_region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), index=True)
    internal: Mapped[bool] = mapped_column(Boolean, default=False)
    message: Mapped[str] = mapped_column(Text)
    reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)


class AlertDelivery(Base):
    __tablename__ = "alert_deliveries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    alert_id: Mapped[int] = mapped_column(ForeignKey("alerts.id"), index=True)
    channel: Mapped[str] = mapped_column(String(32))
    recipient: Mapped[str] = mapped_column(String(64))
    status: Mapped[DeliveryStatus] = mapped_column(_enum(DeliveryStatus))
    error: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------- Warga ----------

class Resident(Base):
    __tablename__ = "residents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), unique=True)
    address_note: Mapped[str | None] = mapped_column(String(255))
    phone: Mapped[str | None] = mapped_column(String(32))
    has_smartphone: Mapped[bool] = mapped_column(Boolean, default=True)
    vulnerability: Mapped[list] = mapped_column(JSON, default=list)
    assistance_notes: Mapped[str | None] = mapped_column(Text)  # sensitif
    buddy_name: Mapped[str | None] = mapped_column(String(120))
    buddy_phone: Mapped[str | None] = mapped_column(String(32))
    consent: Mapped[bool] = mapped_column(Boolean, default=False)
    # lokasi sensitif: hanya koordinator wilayahnya & relawan yang ditugaskan
    home_lat: Mapped[float | None] = mapped_column(Double)
    home_lng: Mapped[float | None] = mapped_column(Double)
    last_lat: Mapped[float | None] = mapped_column(Double)  # dibagikan warga secara sadar
    last_lng: Mapped[float | None] = mapped_column(Double)
    last_location_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ResidentStatusLog(Base):
    """Append-only: status terbaru = baris dengan id terbesar."""

    __tablename__ = "resident_statuses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    resident_id: Mapped[int] = mapped_column(ForeignKey("residents.id"), index=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"), index=True)
    status: Mapped[SafetyStatus] = mapped_column(_enum(SafetyStatus))
    source: Mapped[StatusSource] = mapped_column(_enum(StatusSource))
    need_type: Mapped[NeedType | None] = mapped_column(_enum(NeedType))
    note: Mapped[str | None] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(Double)
    lng: Mapped[float | None] = mapped_column(Double)
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ---------- Shelter, cuaca, aturan ----------

class Shelter(Base):
    __tablename__ = "shelters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), index=True)
    lat: Mapped[float] = mapped_column(Double)
    lng: Mapped[float] = mapped_column(Double)
    address: Mapped[str] = mapped_column(String(255))
    capacity: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[ShelterStatus] = mapped_column(_enum(ShelterStatus))
    contact: Mapped[str | None] = mapped_column(String(120))
    accessibility_note: Mapped[str | None] = mapped_column(String(255))
    is_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class WeatherContext(Base):
    __tablename__ = "weather_contexts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str] = mapped_column(String(255))
    source: Mapped[str] = mapped_column(String(120))
    source_mode: Mapped[SourceMode] = mapped_column(_enum(SourceMode))
    valid_until: Mapped[datetime | None] = mapped_column(DateTime)
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TaskType(StrEnum):
    EVAKUASI = "evakuasi"
    MEDIS = "medis"
    LOGISTIK = "logistik"
    DAMKAR = "damkar"
    SAR = "sar"
    LAINNYA = "lainnya"


class TaskStatus(StrEnum):
    BARU = "baru"  # belum ada relawan
    MENUNGGU = "menunggu_penerimaan"
    DITERIMA = "diterima"
    MENUJU = "menuju_lokasi"
    DITANGANI = "dalam_penanganan"
    SELESAI = "selesai"
    GAGAL = "gagal"
    DIBATALKAN = "dibatalkan"


class Priority(StrEnum):
    KRITIS = "kritis"
    TINGGI = "tinggi"
    SEDANG = "sedang"
    RENDAH = "rendah"


class HazardKind(StrEnum):
    TERTUTUP = "jalan_tertutup"
    GENANGAN = "genangan"
    API = "api"
    POHON = "pohon_tumbang"
    KABEL = "kabel_listrik"
    LAINNYA = "lainnya"


class RouteStatus(StrEnum):
    BELUM = "belum_diverifikasi"
    DAPAT_DILALUI = "dilaporkan_dapat_dilalui"
    TERVERIFIKASI = "terverifikasi"
    DITUTUP = "ditutup"


class RescueTask(Base):
    __tablename__ = "rescue_tasks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id"), index=True)
    resident_id: Mapped[int | None] = mapped_column(ForeignKey("residents.id"), index=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), index=True)
    task_type: Mapped[TaskType] = mapped_column(_enum(TaskType))
    priority: Mapped[Priority] = mapped_column(_enum(Priority))
    description: Mapped[str] = mapped_column(Text)
    lat: Mapped[float | None] = mapped_column(Double)
    lng: Mapped[float | None] = mapped_column(Double)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    shelter_id: Mapped[int | None] = mapped_column(ForeignKey("shelters.id"))
    status: Mapped[TaskStatus] = mapped_column(_enum(TaskStatus), index=True)
    result: Mapped[str | None] = mapped_column(Text)
    people_count: Mapped[int | None] = mapped_column(Integer)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ShelterCheckin(Base):
    __tablename__ = "shelter_checkins"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    shelter_id: Mapped[int] = mapped_column(ForeignKey("shelters.id"), index=True)
    resident_id: Mapped[int | None] = mapped_column(ForeignKey("residents.id"))
    name: Mapped[str] = mapped_column(String(120))
    people_count: Mapped[int] = mapped_column(Integer, default=1)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("rescue_tasks.id"))
    checked_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RoadCondition(Base):
    """Titik bahaya/hambatan jalan (FR-052), dipakai untuk peringatan rute."""

    __tablename__ = "road_conditions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), index=True)
    kind: Mapped[HazardKind] = mapped_column(_enum(HazardKind))
    lat: Mapped[float] = mapped_column(Double)
    lng: Mapped[float] = mapped_column(Double)
    note: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    source_mode: Mapped[SourceMode] = mapped_column(_enum(SourceMode))
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class EvacuationRoute(Base):
    """Rute evakuasi yang digambar & ditinjau koordinator (FR-053)."""

    __tablename__ = "evacuation_routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    region_id: Mapped[int] = mapped_column(ForeignKey("regions.id"), index=True)
    shelter_id: Mapped[int] = mapped_column(ForeignKey("shelters.id"))
    points: Mapped[list] = mapped_column(JSON)  # [[lat, lng], ...]
    status: Mapped[RouteStatus] = mapped_column(_enum(RouteStatus))
    note: Mapped[str | None] = mapped_column(String(255))
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RuleConfig(Base):
    __tablename__ = "rule_configs"

    hazard: Mapped[Hazard] = mapped_column(_enum(Hazard), primary_key=True)
    params: Mapped[dict] = mapped_column(JSON)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
