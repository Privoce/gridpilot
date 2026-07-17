from __future__ import annotations

import os
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]
IS_VERCEL = os.getenv("VERCEL") == "1"
# Vercel’s filesystem is read-only except /tmp
DATA_ROOT = Path(os.getenv("GRIDPILOT_DATA_DIR", "/tmp/gridpilot" if IS_VERCEL else str(ROOT)))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    xai_api_key: str = ""
    xai_model: str = "grok-4.5"
    xai_base_url: str = "https://api.x.ai/v1"
    host: str = "0.0.0.0"
    port: int = 8000
    secret_key: str = "dev-change-me-gridpilot-secret"
    database_url: str = ""
    upload_dir: Path = Path()
    report_dir: Path = Path()
    rules_dir: Path = Path(__file__).resolve().parent / "rules"
    max_pages: int = 6
    session_cookie: str = "gp_session"
    session_max_age: int = 60 * 60 * 24 * 14  # 14 days
    free_audit_limit: int = 25
    free_project_limit: int = 5
    pro_audit_limit: int = 500
    cookie_secure: bool = False

    @property
    def is_vercel(self) -> bool:
        return IS_VERCEL

    @property
    def use_secure_cookies(self) -> bool:
        return self.cookie_secure or self.is_vercel


def _build_settings() -> Settings:
    s = Settings()
    data = DATA_ROOT
    data.mkdir(parents=True, exist_ok=True)
    if not s.database_url:
        s.database_url = f"sqlite:///{data / 'gridpilot.db'}"
    if not s.upload_dir or s.upload_dir == Path():
        s.upload_dir = data / "uploads"
    if not s.report_dir or s.report_dir == Path():
        s.report_dir = data / "reports"
    s.upload_dir.mkdir(parents=True, exist_ok=True)
    s.report_dir.mkdir(parents=True, exist_ok=True)
    return s


settings = _build_settings()
