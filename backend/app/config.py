from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


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
    database_url: str = f"sqlite:///{ROOT / 'data' / 'gridpilot.db'}"
    upload_dir: Path = ROOT / "uploads"
    report_dir: Path = ROOT / "reports"
    rules_dir: Path = Path(__file__).resolve().parent / "rules"
    max_pages: int = 6
    session_cookie: str = "gp_session"
    session_max_age: int = 60 * 60 * 24 * 14  # 14 days
    free_audit_limit: int = 25
    free_project_limit: int = 5
    pro_audit_limit: int = 500


settings = Settings()
settings.upload_dir.mkdir(parents=True, exist_ok=True)
settings.report_dir.mkdir(parents=True, exist_ok=True)
(ROOT / "data").mkdir(parents=True, exist_ok=True)
