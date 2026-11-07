import os
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


ENV_FILE = os.environ.get("RIKSA_ENV_FILE", ".env")  # tes memakai "" = tidak membaca .env


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ENV_FILE or None, extra="ignore")

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings,
                                   file_secret_settings):
        # .env proyek menang atas env var terminal: sisa `TELEGRAM_MODE=mock` di terminal pernah membuat
        # notifikasi Telegram diam-diam tidak terkirim. Env var tetap dipakai untuk kunci yang tidak ada di .env.
        return init_settings, dotenv_settings, env_settings, file_secret_settings

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

    # SMS (PRD v2 §7.3). mock = hanya dicatat. live = POST JSON {to, message, sender} ke sms_api_url dengan
    # header Authorization: Bearer <sms_api_key>. Sesuaikan adaptor di services/notifier.py dengan penyedia pilihan (D-03).
    sms_mode: Literal["mock", "live"] = "mock"
    sms_api_url: str = ""
    sms_api_key: str = ""
    sms_sender: str = "RIKSAWARGA"

    # Parameter awal untuk diuji (asumsi, PRD D-02/D-06), bukan ambang ilmiah
    danger_radius_m: float = 1500  # zona berbahaya = radius dari pos pantau berkondisi Meluap
    unconfirmed_minutes: int = 15  # tak menjawab selama ini setelah Mode Bencana -> Diduga Butuh Bantuan
    condition_stale_hours: float = 6  # kondisi sungai tanpa pembaruan lebih lama = belum diperbarui
    announcement_ttl_hours: float = 12  # pengumuman Meluap memicu Mode Bencana selama ini
    location_retention_hours: float = 72  # lokasi terkini dihapus bila tak ada bencana aktif

    # Simulator TMA langsung untuk semua pos (demo, sensor belum terpasang). 0 = mati. Data berlabel SIMULASI.
    live_sim_seconds: int = 3


settings = Settings()
