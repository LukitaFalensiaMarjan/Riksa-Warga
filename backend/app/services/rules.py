from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app.models import Hazard, RegionLevel, RuleConfig

RULES_NOTE = "Parameter adalah asumsi konfigurasi untuk diuji (PRD §9.3), bukan ambang ilmiah."

DEFAULT_WEIGHTS = {
    "dasar": 10,
    "foto": 15,
    "pelapor_lain": 10,
    "pelapor_lain_maks": 30,
    "hulu": 15,
    "pos_pantau_ambang": 15,
    "cuaca": 10,
    "sumber_petugas": 10,
    "reputasi": 5,
    "reputasi_maks": 15,
    "verifikasi": 20,
}


class RuleParams(BaseModel):
    radius_m: float = Field(gt=0, le=20000)
    window_minutes: int = Field(gt=0, le=1440)
    duplicate_radius_m: float = Field(gt=0, le=5000)
    duplicate_window_minutes: int = Field(gt=0, le=1440)
    upstream_radius_m: float = Field(gt=0, le=20000)
    waspada_min_reporters: int = Field(ge=1, le=50)
    siaga_min_reporters: int = Field(ge=1, le=50)
    siaga_requires_upstream: bool
    siaga_requires_weather: bool
    waspada_timeout_minutes: int = Field(ge=1, le=120)
    audience_level: RegionLevel
    weights: dict[str, int] = Field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    @model_validator(mode="after")
    def _check(self):
        if self.siaga_min_reporters < self.waspada_min_reporters:
            raise ValueError("siaga_min_reporters tidak boleh lebih kecil dari waspada_min_reporters")
        missing = set(DEFAULT_WEIGHTS) - set(self.weights)
        if missing:
            raise ValueError(f"bobot belum lengkap: {sorted(missing)}")
        return self


DEFAULT_RULES: dict[Hazard, RuleParams] = {
    Hazard.BANJIR: RuleParams(
        radius_m=1000, window_minutes=120, duplicate_radius_m=200, duplicate_window_minutes=30,
        upstream_radius_m=1000, waspada_min_reporters=2, siaga_min_reporters=3,
        siaga_requires_upstream=True, siaga_requires_weather=True, waspada_timeout_minutes=5,
        audience_level=RegionLevel.KELURAHAN,
    ),
    Hazard.KEBAKARAN: RuleParams(
        radius_m=500, window_minutes=60, duplicate_radius_m=100, duplicate_window_minutes=30,
        upstream_radius_m=1000, waspada_min_reporters=2, siaga_min_reporters=3,
        siaga_requires_upstream=False, siaga_requires_weather=False, waspada_timeout_minutes=5,
        audience_level=RegionLevel.RW,
    ),
}


def get_rules(db: Session, hazard: Hazard) -> RuleParams:
    row = db.get(RuleConfig, hazard)
    return RuleParams(**row.params) if row else DEFAULT_RULES[hazard]
