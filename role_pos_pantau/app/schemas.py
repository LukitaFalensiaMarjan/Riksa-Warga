from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, model_validator

from app.models import (
    RiverLevel,
    AlertKind,
    AlertLevel,
    DeliveryStatus,
    Hazard,
    HazardKind,
    IncidentStatus,
    NeedType,
    Priority,
    RegionLevel,
    ReportSource,
    ReportStatus,
    RiverCondition,
    Role,
    RouteStatus,
    SafetyStatus,
    ShelterStatus,
    SourceMode,
    StatusSource,
    TaskStatus,
    TaskType,
    Verification,
    Vulnerability,
    WaterCondition,
)

Lat = Field(ge=-90, le=90)
Lng = Field(ge=-180, le=180)


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# ---------- Auth, akun, wilayah ----------

class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: Role


class UserOut(ORM):
    id: int
    username: str
    name: str
    role: Role
    region_id: int
    is_active: bool


class MeOut(UserOut):
    phone: str | None
    telegram_chat_id: str | None


class ProfileUpdate(BaseModel):
    """FR-005: kanal kontak sendiri. Hanya field yang dikirim yang diubah; string kosong = hapus."""

    phone: str | None = Field(default=None, max_length=32)
    telegram_chat_id: str | None = Field(default=None, max_length=64, pattern=r"^(-?\d{1,20})?$")


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[a-z0-9_.]+$")
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=8, max_length=72)  # batas input bcrypt
    role: Role
    region_id: int
    phone: str | None = Field(default=None, max_length=32)
    telegram_chat_id: str | None = Field(default=None, max_length=64)


class ReasonIn(BaseModel):
    reason: str = Field(min_length=3, max_length=500)


DeactivateIn = ReasonIn


class NoteIn(BaseModel):
    note: str | None = Field(default=None, max_length=500)


class RegionOut(ORM):
    id: int
    parent_id: int | None
    name: str
    level: RegionLevel


class RegionCreate(BaseModel):
    parent_id: int | None = None
    name: str = Field(min_length=1, max_length=120)
    level: RegionLevel


class AuditLogOut(ORM):
    id: int
    actor_id: int | None
    action: str
    entity_type: str
    entity_id: str | None
    old_value: dict | None
    new_value: dict | None
    reason: str | None
    created_at: datetime


# ---------- Laporan ----------

class ReportCreate(BaseModel):
    hazard: Hazard = Hazard.BANJIR  # satu-satunya jenis bencana (PRD v2)
    title: str | None = Field(default=None, min_length=3, max_length=120)  # judul laporan dari pelapor
    water_condition: WaterCondition | None = None  # kondisi air sungai yang dilihat
    description: str = Field(min_length=5, max_length=2000)
    lat: float = Lat
    lng: float = Lng
    gps_lat: float | None = Field(default=None, ge=-90, le=90)
    gps_lng: float | None = Field(default=None, ge=-180, le=180)
    reported_at: AwareDatetime | None = None  # wajib berzona, mis. 2026-11-07T14:00:00+07:00
    station_id: int | None = None  # area pos pantau tempat kejadian (utama; wilayah diambil dari pos)
    region_id: int | None = None  # cadangan bila tanpa area pos: RT/RW lokasi kejadian, bukan alamat rumah
    source_mode: SourceMode = SourceMode.REAL
    from_sensor: bool = False  # hanya pos pantau
    client_ref: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")  # antrean offline

    @model_validator(mode="after")
    def _check(self):
        if (self.gps_lat is None) != (self.gps_lng is None):
            raise ValueError("gps_lat dan gps_lng harus diisi bersama")
        if self.station_id is None and self.region_id is None:
            raise ValueError("Pilih area pos pantau lokasi kejadian")
        return self


class NearStationIn(BaseModel):
    station_id: int | None = None  # pos pantau (sungai) terdekat dari tempat warga


class ScoreFactor(BaseModel):
    faktor: str
    poin: int
    keterangan: str


class ReportMineOut(ORM):
    id: int
    incident_id: int | None
    hazard: Hazard
    title: str | None = None
    water_condition: str | None = None
    description: str
    source_mode: SourceMode
    status: ReportStatus
    status_reason: str | None
    reported_at: datetime
    received_at: datetime
    has_photo: bool
    station_id: int | None = None
    station_name: str | None = None
    duplicate_of: int | None = None


class ReportOut(ReportMineOut):
    reporter_id: int
    region_id: int
    source: ReportSource
    lat: float
    lng: float
    gps_lat: float | None
    gps_lng: float | None
    is_upstream: bool
    score: int
    score_factors: list[ScoreFactor]
    flags: list[str]
    reviewed_by: int | None
    reviewed_at: datetime | None


# ---------- Pos pantau ----------

class StationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    region_id: int
    lat: float = Lat
    lng: float = Lng
    is_upstream: bool = False
    river_name: str | None = Field(default=None, max_length=120)
    warning_cm: float = Field(gt=0, le=5000)
    danger_cm: float = Field(gt=0, le=5000)

    @model_validator(mode="after")
    def _check(self):
        if self.danger_cm <= self.warning_cm:
            raise ValueError("danger_cm harus lebih besar dari warning_cm")
        return self


class ObservationCreate(BaseModel):
    level_cm: float = Field(ge=0, le=5000)
    river_condition: RiverCondition = RiverCondition.NORMAL
    note: str | None = Field(default=None, max_length=500)
    observed_at: AwareDatetime | None = None
    source_mode: SourceMode = SourceMode.REAL


class ObservationOut(ORM):
    id: int
    station_id: int
    level_cm: float
    unit: str = "cm"
    river_condition: RiverCondition
    note: str | None
    source_mode: SourceMode
    observed_at: datetime
    received_at: datetime
    reported_by: int


class ConditionOut(BaseModel):
    status: RiverLevel
    set_at: datetime
    set_by: int
    note: str | None
    source_mode: SourceMode
    stale: bool


class StationOut(ORM):
    id: int
    name: str
    region_id: int
    lat: float
    lng: float
    is_upstream: bool
    river_name: str | None
    warning_cm: float
    danger_cm: float
    latest: ObservationOut | None
    status: str  # normal | waspada | bahaya | data_kedaluwarsa | tidak_ada_data
    stale: bool
    condition: "ConditionOut | None" = None  # kondisi sungai 3 tingkat dari pos pantau


class TrendOut(BaseModel):
    station_id: int
    unit: str = "cm"
    direction: str  # naik | stabil | turun | belum_cukup_data
    status: str
    stale: bool
    readings: list[ObservationOut]


# ---------- Kejadian & alert ----------

class IncidentOut(ORM):
    id: int
    hazard: Hazard
    region_id: int
    lat: float
    lng: float
    status: IncidentStatus
    level: AlertLevel
    verification: Verification
    pending_level: AlertLevel | None
    pending_since: datetime | None
    is_simulation: bool
    score: int
    unique_reporters: int
    started_at: datetime
    last_report_at: datetime


class IncidentDetail(IncidentOut):
    reports: list[ReportOut]


class LevelIn(ReasonIn):
    level: AlertLevel


class AlertOut(ORM):
    id: int
    incident_id: int | None
    station_id: int | None
    kind: AlertKind
    level: AlertLevel | None
    verification: Verification | None
    audience_region_id: int
    internal: bool
    message: str
    reason: str | None
    created_by: int | None
    created_at: datetime
    severity: str | None = None
    sms: bool = False
    parent_id: int | None = None


class DeliveryOut(ORM):
    id: int
    alert_id: int
    channel: str
    recipient: str
    status: DeliveryStatus
    error: str | None
    created_at: datetime


# ---------- Warga ----------

class ResidentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    region_id: int
    user_id: int | None = None
    household: str | None = Field(default=None, max_length=120)  # nama keluarga / kepala keluarga
    address_note: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    has_smartphone: bool = True
    vulnerability: list[Vulnerability] = []
    assistance_notes: str | None = Field(default=None, max_length=1000)
    buddy_name: str | None = Field(default=None, max_length=120)
    buddy_phone: str | None = Field(default=None, max_length=32)
    consent: bool = False
    home_lat: float | None = Field(default=None, ge=-90, le=90)
    home_lng: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def _pair(self):
        if (self.home_lat is None) != (self.home_lng is None):
            raise ValueError("home_lat dan home_lng harus diisi bersama")
        return self


class ResidentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    region_id: int | None = None
    address_note: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    has_smartphone: bool | None = None
    vulnerability: list[Vulnerability] | None = None
    assistance_notes: str | None = Field(default=None, max_length=1000)
    buddy_name: str | None = Field(default=None, max_length=120)
    buddy_phone: str | None = Field(default=None, max_length=32)
    consent: bool | None = None
    home_lat: float | None = Field(default=None, ge=-90, le=90)
    home_lng: float | None = Field(default=None, ge=-180, le=180)


class ResidentOut(BaseModel):
    id: int
    name: str
    region_id: int
    user_id: int | None
    household: str | None = None
    location_consent: bool = False
    address_note: str | None
    phone: str | None
    has_smartphone: bool
    vulnerability: list[Vulnerability]
    buddy_name: str | None
    buddy_phone: str | None
    consent: bool
    latest_status: SafetyStatus
    latest_status_at: datetime | None
    latest_status_source: StatusSource | None
    latest_need_type: NeedType | None
    home_lat: float | None
    home_lng: float | None
    last_lat: float | None
    last_lng: float | None
    last_location_at: datetime | None


class ResidentDetail(ResidentOut):
    assistance_notes: str | None


class StatusUpdateIn(BaseModel):
    """Dicatat koordinator/buddy/keluarga/petugas, termasuk untuk warga tanpa smartphone."""

    status: SafetyStatus
    source: StatusSource = StatusSource.KOORDINATOR
    need_type: NeedType | None = None
    note: str | None = Field(default=None, max_length=500)
    incident_id: int | None = None

    @model_validator(mode="after")
    def _check(self):
        if self.source == StatusSource.MANDIRI:
            raise ValueError("sumber 'mandiri' hanya lewat /me/status")
        if self.status == SafetyStatus.AMAN_MANDIRI:
            raise ValueError("aman_mandiri hanya dari laporan warga sendiri")
        if self.status in (SafetyStatus.AMAN_TERVERIFIKASI, SafetyStatus.TIDAK_DAPAT_DIHUBUNGI) and not self.note:
            raise ValueError("note wajib: catat metode verifikasi / upaya kontak")
        if self.status == SafetyStatus.BUTUH_BANTUAN and self.need_type is None:
            raise ValueError("need_type wajib untuk butuh_bantuan")
        return self


class SelfStatusIn(BaseModel):
    status: Literal["aman", "butuh_bantuan"]
    need_type: NeedType | None = None
    note: str | None = Field(default=None, max_length=500)
    incident_id: int | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)  # opsional: dibagikan warga bersama status
    lng: float | None = Field(default=None, ge=-180, le=180)

    @model_validator(mode="after")
    def _check(self):
        if self.status == "butuh_bantuan" and self.need_type is None:
            raise ValueError("need_type wajib untuk butuh_bantuan")
        if (self.lat is None) != (self.lng is None):
            raise ValueError("lat dan lng harus diisi bersama")
        return self


class LocationIn(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    kind: Literal["terkini", "rumah"] = "terkini"


class StatusLogOut(ORM):
    id: int
    resident_id: int
    incident_id: int | None
    status: SafetyStatus
    source: StatusSource
    need_type: NeedType | None
    note: str | None
    lat: float | None
    lng: float | None
    updated_by: int
    created_at: datetime


class HelpRequestOut(BaseModel):
    resident: ResidentOut
    is_vulnerable: bool
    need_type: NeedType | None
    note: str | None
    requested_at: datetime
    source: StatusSource


class StatusSummaryOut(BaseModel):
    incident_id: int | None
    total: int
    by_status: dict[SafetyStatus, int]


# ---------- Shelter, cuaca, aturan ----------

class ShelterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    region_id: int
    lat: float = Lat
    lng: float = Lng
    address: str = Field(min_length=1, max_length=255)
    capacity: int | None = Field(default=None, ge=0)
    contact: str | None = Field(default=None, max_length=120)
    accessibility_note: str | None = Field(default=None, max_length=255)


class ShelterOut(ORM):
    id: int
    name: str
    region_id: int
    lat: float
    lng: float
    address: str
    capacity: int | None
    status: ShelterStatus
    contact: str | None
    accessibility_note: str | None
    is_verified: bool
    verified_at: datetime | None
    updated_at: datetime
    occupancy: int = 0  # jumlah orang yang check-in


class ShelterStatusIn(BaseModel):
    status: ShelterStatus
    note: str | None = Field(default=None, max_length=500)


class WeatherIn(BaseModel):
    region_id: int
    is_active: bool
    description: str = Field(min_length=3, max_length=255)
    source: str = Field(default="BMKG (input manual)", max_length=120)
    source_mode: SourceMode = SourceMode.REAL
    valid_until: AwareDatetime | None = None


class WeatherOut(ORM):
    id: int
    region_id: int
    is_active: bool
    description: str
    source: str
    source_mode: SourceMode
    valid_until: datetime | None
    updated_by: int
    updated_at: datetime


class RuleOut(BaseModel):
    hazard: Hazard
    params: dict
    is_default: bool
    note: str


class CheckinIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    people_count: int = Field(default=1, ge=1, le=500)
    resident_id: int | None = None


class CheckinOut(ORM):
    id: int
    shelter_id: int
    resident_id: int | None
    name: str
    people_count: int
    task_id: int | None
    checked_by: int
    created_at: datetime


# ---------- Tugas relawan ----------

class TaskCreate(BaseModel):
    task_type: TaskType
    priority: Priority = Priority.SEDANG
    description: str = Field(min_length=3, max_length=1000)
    resident_id: int | None = None
    incident_id: int | None = None
    region_id: int | None = None  # default: wilayah warga, atau wajib bila tanpa warga
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    assignee_id: int | None = None
    shelter_id: int | None = None


class TaskAssignIn(BaseModel):
    assignee_id: int


class TaskUpdateIn(BaseModel):
    status: TaskStatus
    note: str | None = Field(default=None, max_length=1000)  # wajib untuk selesai/gagal/dibatalkan
    people_count: int | None = Field(default=None, ge=0, le=500)
    shelter_id: int | None = None


class TaskOut(ORM):
    id: int
    incident_id: int | None
    resident_id: int | None
    resident_name: str | None = None
    resident_vulnerability: list[str] = []
    region_id: int
    task_type: TaskType
    priority: Priority
    description: str
    lat: float | None
    lng: float | None
    assignee_id: int | None
    assignee_name: str | None = None
    shelter_id: int | None
    status: TaskStatus
    result: str | None
    people_count: int | None
    created_by: int
    created_at: datetime
    updated_at: datetime


# ---------- Jalan & rute ----------

class RoadConditionIn(BaseModel):
    region_id: int
    kind: HazardKind
    lat: float = Lat
    lng: float = Lng
    note: str | None = Field(default=None, max_length=255)
    source_mode: SourceMode = SourceMode.REAL


class RoadConditionOut(ORM):
    id: int
    region_id: int
    kind: HazardKind
    lat: float
    lng: float
    note: str | None
    is_active: bool
    source_mode: SourceMode
    created_by: int
    created_at: datetime
    updated_at: datetime


class EvacRouteIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    region_id: int
    shelter_id: int
    points: list[tuple[float, float]] = Field(min_length=2, max_length=500)
    note: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def _check(self):
        if any(not (-90 <= a <= 90 and -180 <= b <= 180) for a, b in self.points):
            raise ValueError("koordinat rute tidak valid")
        return self


class EvacRouteStatusIn(BaseModel):
    status: RouteStatus
    note: str | None = Field(default=None, max_length=255)


class EvacRouteOut(ORM):
    id: int
    name: str
    region_id: int
    shelter_id: int
    points: list[list[float]]
    status: RouteStatus
    note: str | None
    verified_by: int | None
    verified_at: datetime | None
    updated_at: datetime
