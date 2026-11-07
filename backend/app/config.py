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
    simulator_interval_seconds: int = 3  # 0 = matikan loop auto-generate pengamatan sungai tiap 3 detik

    # Rute jalan kaki OSRM. Kosongkan untuk mematikan (hanya garis lurus). Koordinat pengguna dikirim ke layanan ini.
    routing_url: str = "https://routing.openstreetmap.de/routed-foot/route/v1/foot"
    tile_url: str = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    tile_attribution: str = "© OpenStreetMap contributors"

    telegram_mode: Literal["mock", "live"] = "mock"
    telegram_bot_token: str = ""
    telegram_default_chat_id: str = ""  # grup uji opsional untuk alert publik

    # SMS (PRD §7.3). mock = hanya dicatat; twilio = kirim sungguhan. Batas per nomor per jam: anti-spam & biaya.
    sms_mode: Literal["mock", "twilio"] = "mock"
    sms_max_per_hour: int = 4
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from: str = ""
    twilio_messaging_service_sid: str = ""

    # Prakiraan & Mode Bencana (semua adalah asumsi uji, PRD §7.1 / §9.3 / D-05 / D-06 / D-10)
    forecast_url: str = "https://api.open-meteo.com/v1/forecast"
    hazard_radius_m: int = 800  # zona berbahaya di sekitar pos berstatus Meluap (D-02)
    diduga_minutes: int = 15  # tak menjawab selama N menit di zona berbahaya -> Diduga Butuh Bantuan (D-06)
    mode_hours: int = 6  # pengumuman Waspada+ menyalakan Mode Bencana selama N jam
    location_retention_hours: int = 24  # lokasi terakhir warga dihapus setelah N jam (D-10)
    condition_stale_hours: int = 6  # kondisi sungai tak diperbarui > N jam ditandai "belum diperbarui"


settings = Settings()
