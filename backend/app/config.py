from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "mysql+pymysql://root:@127.0.0.1:3306/riksa_warga?charset=utf8mb4"
    jwt_secret: str  # wajib dari .env, tidak ada default agar tidak bocor ke produksi
    jwt_expire_minutes: int = 720
    seed_password: str = ""

    upload_dir: str = "uploads"
    max_upload_mb: int = 5
    report_rate_limit_per_10min: int = 10
    observation_stale_minutes: int = 30
    engine_tick_seconds: int = 30  # 0 = matikan loop timer eskalasi

    # Rute jalan kaki OSRM. Kosongkan untuk mematikan (hanya garis lurus). Koordinat pengguna dikirim ke layanan ini.
    routing_url: str = "https://routing.openstreetmap.de/routed-foot/route/v1/foot"
    tile_url: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    tile_attribution: str = "© OpenStreetMap contributors"

    telegram_mode: Literal["mock", "live"] = "mock"
    telegram_bot_token: str = ""
    telegram_default_chat_id: str = ""  # grup uji opsional untuk alert publik


settings = Settings()
