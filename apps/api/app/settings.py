import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import URL
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(PROJECT_ROOT / ".env")
load_dotenv(PROJECT_ROOT / ".env.smtp-import")


def load_spring_mail_config() -> dict:
    config_path = os.getenv("NERVA_SPRING_MAIL_CONFIG")
    if not config_path:
        return {}
    try:
        content = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
        return content.get("spring", {}).get("mail", {}) or {}
    except (OSError, UnicodeError, yaml.YAMLError):
        return {}


spring_mail = load_spring_mail_config()


@dataclass(frozen=True)
class Settings:
    ai_provider: str = os.getenv("NERVA_AI_PROVIDER", "local")
    dashscope_api_key: str | None = os.getenv("DASHSCOPE_API_KEY")
    dashscope_base_url: str = os.getenv(
        "DASHSCOPE_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    text_model: str = os.getenv("NERVA_TEXT_MODEL", "qwen3.6-flash")
    ocr_model: str = os.getenv("NERVA_OCR_MODEL", "qwen3.5-ocr")
    embedding_model: str = os.getenv("NERVA_EMBEDDING_MODEL", "text-embedding-v4")
    rerank_model: str = os.getenv("NERVA_RERANK_MODEL", "qwen3-rerank")
    database_url: str | None = os.getenv("DATABASE_URL") or None
    db_host: str = os.getenv("POSTGRES_HOST", "127.0.0.1")
    db_port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    db_name: str = os.getenv("POSTGRES_DB", "nerva")
    db_user: str = os.getenv("POSTGRES_USER", "postgres")
    db_password: str | None = os.getenv("POSTGRES_PASSWORD") or None
    session_cookie_name: str = os.getenv("NERVA_SESSION_COOKIE", "nerva_session")
    session_cookie_secure: bool = os.getenv("NERVA_COOKIE_SECURE", "false").lower() == "true"
    session_days: int = int(os.getenv("NERVA_SESSION_DAYS", "7"))
    cors_origins: tuple[str, ...] = tuple(
        value.strip()
        for value in os.getenv(
            "NERVA_CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
        if value.strip()
    )
    verification_code_secret: str = os.getenv("NERVA_CODE_SECRET", "nerva-local-development-only")
    smtp_host: str | None = os.getenv("SMTP_HOST") or spring_mail.get("host") or None
    smtp_port: int = int(os.getenv("SMTP_PORT") or spring_mail.get("port") or 465)
    smtp_username: str | None = os.getenv("SMTP_USERNAME") or str(spring_mail.get("username") or "") or None
    smtp_password: str | None = os.getenv("SMTP_PASSWORD") or str(spring_mail.get("password") or "") or None
    smtp_from_name: str = os.getenv("SMTP_FROM_NAME", "Nerva 团队")
    smtp_use_ssl: bool = os.getenv("SMTP_USE_SSL", "true").lower() == "true"

    def validate(self) -> None:
        if self.ai_provider != "local" and not self.dashscope_api_key:
            raise RuntimeError("DASHSCOPE_API_KEY is required when cloud AI is enabled")

    def sqlalchemy_url(self) -> str | URL:
        if self.database_url:
            return self.database_url
        if not self.db_password:
            raise RuntimeError(
                "PostgreSQL is not configured. Copy .env.example to .env and set "
                "POSTGRES_PASSWORD, or provide DATABASE_URL."
            )
        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_password,
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )


settings = Settings()
