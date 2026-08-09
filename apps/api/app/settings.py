import os
import ipaddress
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
TAURI_DESKTOP_ORIGIN = "http://tauri.localhost"


def trusted_cors_origins() -> tuple[str, ...]:
    configured = (
        value.strip()
        for value in os.getenv(
            "NERVA_CORS_ORIGINS",
            "http://localhost:5173,http://127.0.0.1:5173",
        ).split(",")
    )
    return tuple(dict.fromkeys((*filter(None, configured), TAURI_DESKTOP_ORIGIN)))


@dataclass(frozen=True)
class Settings:
    environment: str = os.getenv("NERVA_ENV", "development").strip().lower()
    service_version: str = os.getenv("NERVA_VERSION", "0.1.0").strip()
    sentry_dsn: str | None = os.getenv("NERVA_SENTRY_DSN") or None
    sentry_traces_sample_rate: float = float(os.getenv("NERVA_SENTRY_TRACES_SAMPLE_RATE", "0.1"))
    metrics_token: str | None = os.getenv("NERVA_METRICS_TOKEN") or None
    metrics_allowed_networks: tuple[str, ...] = tuple(
        value.strip() for value in os.getenv(
            "NERVA_METRICS_ALLOWED_NETWORKS", "127.0.0.1/32,::1/128",
        ).split(",") if value.strip()
    )
    log_format: str = os.getenv("NERVA_LOG_FORMAT", "text").strip().lower()
    log_dir: str | None = os.getenv("NERVA_LOG_DIR") or None
    ai_provider: str = os.getenv("NERVA_AI_PROVIDER", "local")
    dashscope_api_key: str | None = os.getenv("DASHSCOPE_API_KEY")
    dashscope_base_url: str = os.getenv(
        "DASHSCOPE_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    text_model: str = os.getenv("NERVA_TEXT_MODEL", "qwen3.7-plus")
    research_model: str = os.getenv("NERVA_RESEARCH_MODEL", "").strip() or os.getenv(
        "NERVA_TEXT_MODEL", "qwen3.7-plus",
    )
    ocr_model: str = os.getenv("NERVA_OCR_MODEL", "qwen3.5-ocr")
    embedding_model: str = os.getenv("NERVA_EMBEDDING_MODEL", "text-embedding-v4")
    rerank_model: str = os.getenv("NERVA_RERANK_MODEL", "qwen3-rerank")
    embedding_base_url: str = os.getenv(
        "NERVA_EMBEDDING_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    rerank_base_url: str = os.getenv(
        "NERVA_RERANK_BASE_URL",
        "https://dashscope.aliyuncs.com/compatible-api/v1",
    )
    embedding_batch_size: int = int(os.getenv("NERVA_EMBEDDING_BATCH_SIZE", "10"))
    embedding_timeout_seconds: float = float(os.getenv("NERVA_EMBEDDING_TIMEOUT_SECONDS", "30"))
    rerank_timeout_seconds: float = float(os.getenv("NERVA_RERANK_TIMEOUT_SECONDS", "30"))
    max_indexed_chunks_per_user: int = int(os.getenv("NERVA_MAX_INDEXED_CHUNKS_PER_USER", "20000"))
    chunk_target_chars: int = int(os.getenv("NERVA_CHUNK_TARGET_CHARS", "900"))
    chunk_overlap_chars: int = int(os.getenv("NERVA_CHUNK_OVERLAP_CHARS", "120"))
    database_url: str | None = os.getenv("DATABASE_URL") or None
    db_host: str = os.getenv("POSTGRES_HOST", "127.0.0.1")
    db_port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    db_name: str = os.getenv("POSTGRES_DB", "nerva")
    db_user: str = os.getenv("POSTGRES_USER", "postgres")
    db_password: str | None = os.getenv("POSTGRES_PASSWORD") or None
    session_cookie_name: str = os.getenv("NERVA_SESSION_COOKIE", "nerva_session")
    session_cookie_secure: bool = os.getenv("NERVA_COOKIE_SECURE", "false").lower() == "true"
    session_days: int = int(os.getenv("NERVA_SESSION_DAYS", "7"))
    cors_origins: tuple[str, ...] = trusted_cors_origins()
    verification_code_secret: str = os.getenv("NERVA_CODE_SECRET", "nerva-local-development-only")
    admin_username: str = os.getenv("NERVA_ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("NERVA_ADMIN_PASSWORD", "admin")
    admin_email: str = os.getenv("NERVA_ADMIN_EMAIL", "admin@nerva.app")
    admin_login_max_failures: int = int(os.getenv("NERVA_ADMIN_LOGIN_MAX_FAILURES", "5"))
    admin_login_window_minutes: int = int(os.getenv("NERVA_ADMIN_LOGIN_WINDOW_MINUTES", "10"))
    index_worker_count: int = int(os.getenv("NERVA_INDEX_WORKERS", "1"))
    index_recovery_age_minutes: int = int(os.getenv("NERVA_INDEX_RECOVERY_AGE_MINUTES", "5"))
    index_recovery_limit: int = int(os.getenv("NERVA_INDEX_RECOVERY_LIMIT", "100"))
    smtp_host: str | None = os.getenv("SMTP_HOST") or spring_mail.get("host") or None
    smtp_port: int = int(os.getenv("SMTP_PORT") or spring_mail.get("port") or 465)
    smtp_username: str | None = os.getenv("SMTP_USERNAME") or str(spring_mail.get("username") or "") or None
    smtp_password: str | None = os.getenv("SMTP_PASSWORD") or str(spring_mail.get("password") or "") or None
    smtp_from_name: str = os.getenv("SMTP_FROM_NAME", "Nerva 团队")
    smtp_use_ssl: bool = os.getenv("SMTP_USE_SSL", "true").lower() == "true"

    def validate(self) -> None:
        if self.environment not in {"development", "test", "production"}:
            raise RuntimeError("NERVA_ENV must be development, test, or production")
        if self.log_format not in {"text", "json"}:
            raise RuntimeError("NERVA_LOG_FORMAT must be text or json")
        if not 0 <= self.sentry_traces_sample_rate <= 1:
            raise RuntimeError("NERVA_SENTRY_TRACES_SAMPLE_RATE must be between 0 and 1")
        try:
            for network in self.metrics_allowed_networks:
                ipaddress.ip_network(network, strict=False)
        except ValueError as exc:
            raise RuntimeError("NERVA_METRICS_ALLOWED_NETWORKS contains an invalid CIDR") from exc
        if self.ai_provider not in {"local", "bailian"}:
            raise RuntimeError(f"Unsupported NERVA_AI_PROVIDER: {self.ai_provider}")
        if self.ai_provider == "bailian":
            if not self.dashscope_api_key:
                raise RuntimeError("DASHSCOPE_API_KEY is required when Bailian AI is enabled")
            if not self.dashscope_base_url.startswith("https://"):
                raise RuntimeError("DASHSCOPE_BASE_URL must use HTTPS")
            if not self.text_model.strip():
                raise RuntimeError("NERVA_TEXT_MODEL is required when Bailian AI is enabled")
            if not self.research_model.strip():
                raise RuntimeError("NERVA_RESEARCH_MODEL must not be blank when configured")
            if not self.ocr_model.strip():
                raise RuntimeError("NERVA_OCR_MODEL is required when Bailian AI is enabled")
            for name, value in (
                ("NERVA_EMBEDDING_BASE_URL", self.embedding_base_url),
                ("NERVA_RERANK_BASE_URL", self.rerank_base_url),
            ):
                if value and not value.startswith("https://"):
                    raise RuntimeError(f"{name} must use HTTPS")
        if self.embedding_batch_size < 1:
            raise RuntimeError("NERVA_EMBEDDING_BATCH_SIZE must be positive")
        if self.chunk_target_chars < 100 or not 0 <= self.chunk_overlap_chars < self.chunk_target_chars:
            raise RuntimeError("chunk target/overlap configuration is invalid")
        if self.max_indexed_chunks_per_user < 1:
            raise RuntimeError("NERVA_MAX_INDEXED_CHUNKS_PER_USER must be positive")
        if self.admin_login_max_failures < 1 or self.admin_login_window_minutes < 1:
            raise RuntimeError("administrator login limits must be positive")
        if self.index_worker_count != 1:
            raise RuntimeError("NERVA_INDEX_WORKERS must remain 1 until a durable task queue is available")
        if self.index_recovery_age_minutes < 1 or self.index_recovery_limit < 1:
            raise RuntimeError("index recovery settings must be positive")
        if self.environment == "production":
            if self.verification_code_secret == "nerva-local-development-only" or len(self.verification_code_secret) < 32:
                raise RuntimeError("NERVA_CODE_SECRET must be a unique value of at least 32 characters")
            if self.admin_password == "admin" or len(self.admin_password) < 16:
                raise RuntimeError("NERVA_ADMIN_PASSWORD must be a non-default value of at least 16 characters")
            if not self.session_cookie_secure:
                raise RuntimeError("NERVA_COOKIE_SECURE must be true in production")
            if self.log_format != "json":
                raise RuntimeError("NERVA_LOG_FORMAT must be json in production")
            if not self.metrics_token or len(self.metrics_token) < 24:
                raise RuntimeError("NERVA_METRICS_TOKEN must contain at least 24 characters in production")
            if not self.metrics_allowed_networks:
                raise RuntimeError("NERVA_METRICS_ALLOWED_NETWORKS is required in production")
            if not self.sentry_dsn:
                raise RuntimeError("NERVA_SENTRY_DSN is required in production")
            if not self.smtp_host or not self.smtp_username or not self.smtp_password:
                raise RuntimeError("SMTP_HOST, SMTP_USERNAME and SMTP_PASSWORD are required in production")
            if not self.cors_origins or "*" in self.cors_origins:
                raise RuntimeError("NERVA_CORS_ORIGINS must explicitly list trusted desktop origins")

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
