"""Environment/secret-file configuration. No credentials are baked into the code."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import quote

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


def secret(name: str, default: str = "") -> str:
    filename = os.getenv(f"{name}_FILE")
    if filename:
        return Path(filename).read_text(encoding="utf-8").strip()
    return os.getenv(name, default).strip()


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "development"
    data_dir: Path = ROOT / "data"
    database_url: str = ""
    redis_url: str = ""
    mqtt_host: str = ""
    mqtt_port: int = 1883
    mqtt_tls: bool = False
    mqtt_user: str = "safewalk"
    minio_endpoint: str = ""
    minio_secure: bool = False
    minio_bucket: str = "safewalk-blackbox"
    device_api_token: str = ""
    caregiver_api_token: str = ""
    telemetry_retention_days: int = 7
    incident_retention_days: int = 30
    hazard_ttl_hours: int = 24
    max_request_bytes: int = 40 * 1024 * 1024
    max_video_bytes: int = 18 * 1024 * 1024
    ws_allowed_origins: str = ""
    camera_height_m: float = 1.65
    camera_horizontal_fov_deg: float = 70.0
    camera_vertical_fov_deg: float = 54.0

    @property
    def production(self) -> bool:
        return self.app_env.lower() == "production"

    def load_secrets(self) -> "Settings":
        self.device_api_token = secret("DEVICE_API_TOKEN", self.device_api_token)
        self.caregiver_api_token = secret("CAREGIVER_API_TOKEN", self.caregiver_api_token)
        if not self.database_url and os.getenv("POSTGRES_PASSWORD_FILE"):
            password = quote(secret("POSTGRES_PASSWORD"), safe="")
            host = os.getenv("POSTGRES_HOST", "db")
            self.database_url = f"postgresql://safewalk:{password}@{host}:5432/safewalk"
        if not self.redis_url and os.getenv("REDIS_PASSWORD_FILE"):
            self.redis_url = f"redis://:{quote(secret('REDIS_PASSWORD'), safe='')}@redis:6379/0"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.production:
            if min(len(self.device_api_token), len(self.caregiver_api_token)) < 32:
                raise ValueError("Production requires two distinct API tokens of at least 32 characters")
            if self.device_api_token == self.caregiver_api_token:
                raise ValueError("Device and caregiver credentials must be different")
            if not all((self.database_url, self.redis_url, self.mqtt_host, self.minio_endpoint)):
                raise ValueError("Production requires PostgreSQL, Redis, MQTT, and MinIO")
            if not secret("ARCHIVE_KEY"):
                raise ValueError("Production requires an ARCHIVE_KEY (64 hex characters)")
        if self.camera_height_m <= 0 or not 10 <= self.camera_vertical_fov_deg < 150:
            raise ValueError("Invalid camera calibration")
        return self
