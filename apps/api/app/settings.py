import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import URL


load_dotenv(Path(__file__).resolve().parents[3] / ".env")


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
