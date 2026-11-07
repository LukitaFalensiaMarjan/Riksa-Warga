import os
import tempfile
from datetime import datetime, timezone

# harus sebelum import app: config wajib JWT_SECRET; tes tidak butuh server MySQL
os.environ.update({
    "RIKSA_ENV_FILE": "",  # jangan baca .env asli (berisi token Telegram live)
    "JWT_SECRET": "test-secret-yang-cukup-panjang-untuk-hs256",
    "DATABASE_URL": "sqlite://",
    "UPLOAD_DIR": tempfile.mkdtemp(prefix="riksa-test-"),
    "TELEGRAM_MODE": "mock",
    "TELEGRAM_BOT_TOKEN": "",
    "TELEGRAM_DEFAULT_CHAT_ID": "",
    "ENGINE_TICK_SECONDS": "0",
    "REPORT_RATE_LIMIT_PER_10MIN": "10",
    "OBSERVATION_STALE_MINUTES": "30",
    "LIVE_SIM_SECONDS": "0",
})

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base, get_db
from app.main import app
from app.models import Region, Resident, Shelter, Station, User
from app.routers import auth as auth_router
from scripts.seed import seed_data

PASSWORD = "password-tes-123"

# Titik uji: dekat pos hulu (< 1 km) dan dekat pos hilir (~2,2 km dari hulu)
HULU = (-6.8805, 107.6102)
HILIR = (-6.9002, 107.6151)
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def aware(dt: datetime) -> str:
    """utcnow() (UTC naive) -> ISO berzona, format yang wajib dikirim klien."""
    return dt.replace(tzinfo=timezone.utc).isoformat()


@pytest.fixture
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Session() as s:
        seed_data(s, PASSWORD)

    def _get_db():
        with Session() as s:
            yield s

    app.dependency_overrides[get_db] = _get_db
    auth_router._fails.clear()
    with Session() as s:
        yield s
    app.dependency_overrides.clear()
    engine.dispose()


@pytest.fixture
def client(db):
    return TestClient(app)


@pytest.fixture
def login(client):
    cache: dict[str, dict[str, str]] = {}

    def _login(username: str) -> dict[str, str]:
        if username not in cache:
            r = client.post("/auth/login", json={"username": username, "password": PASSWORD})
            assert r.status_code == 200, r.text
            cache[username] = {"Authorization": f"Bearer {r.json()['access_token']}"}
        return cache[username]

    return _login


@pytest.fixture
def ids(db):
    out = {u.username: u.id for u in db.scalars(select(User))}
    for model in (Region, Station, Resident, Shelter):
        out.update({row.name: row.id for row in db.scalars(select(model))})
    return out


@pytest.fixture
def report(client, login, db):
    def _report(username: str, hazard: str = "banjir", at: tuple[float, float] = HULU, expect: int = 201, **extra):
        # region_id default = wilayah rumah pelapor; tes lokasi lain mengirim region_id sendiri
        home = db.scalar(select(User.region_id).where(User.username == username))
        body = {"hazard": hazard, "description": "Air sungai naik sampai jalan", "lat": at[0], "lng": at[1],
                "region_id": home, **extra}
        r = client.post("/reports", json=body, headers=login(username))
        assert r.status_code == expect, r.text
        return r.json()

    return _report


@pytest.fixture
def set_chat(db):
    def _set(username: str, chat_id: str | None) -> None:
        user = db.scalar(select(User).where(User.username == username))
        user.telegram_chat_id = chat_id
        db.commit()

    return _set


@pytest.fixture
def set_phone(db):
    def _set(username: str, phone: str | None) -> None:
        user = db.scalar(select(User).where(User.username == username))
        user.phone = phone
        db.commit()

    return _set


@pytest.fixture(autouse=True)
def no_live_weather(monkeypatch):
    """Tes tidak memanggil Open-Meteo sungguhan: default gagal jaringan; tes cuaca memasang data sendiri."""
    from app.services import weather_live

    def offline(params):
        raise OSError("offline dalam tes")

    weather_live.reset_cache()
    monkeypatch.setattr(weather_live, "http_get", offline)
    yield
    weather_live.reset_cache()
