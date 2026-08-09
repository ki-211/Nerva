import contextvars
import json
import logging
import os
import re
import sys
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path


DEFAULT_LOG_DIR = Path(__file__).resolve().parents[3] / "logs"
request_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")
user_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("user_id", default="-")
client_type_var: contextvars.ContextVar[str] = contextvars.ContextVar("client_type", default="unknown")
SENSITIVE_KEY = re.compile(
    r"(^|_)(content|markdown|text|body|data|form|files|query_string|ocr|embedding|password|verification_code|cookie|token|authorization|api_key|email)($|_)",
    re.IGNORECASE,
)


def scrub_sensitive(value, key: str = "", depth: int = 0):
    if SENSITIVE_KEY.search(key):
        return "[Filtered]"
    if depth > 8:
        return "[Truncated]"
    if isinstance(value, str):
        value = re.sub(r"Bearer\s+[A-Za-z0-9._~+/=-]+", "Bearer [Filtered]", value, flags=re.IGNORECASE)
        value = re.sub(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[Filtered email]", value, flags=re.IGNORECASE)
        value = re.sub(
            r"(?i)(password|token|cookie|api[_-]?key)\s*[=:]\s*[^\s,;]+",
            r"\1=[Filtered]", value,
        )
        return value[:4000]
    if isinstance(value, dict):
        return {item_key: scrub_sensitive(item, str(item_key), depth + 1) for item_key, item in value.items()}
    if isinstance(value, list):
        return [scrub_sensitive(item, key, depth + 1) for item in value[:100]]
    return value


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get()
        record.user_id = user_id_var.get()
        record.client_type = client_type_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "environment": os.getenv("NERVA_ENV", "development"),
            "service": "nerva-api",
            "version": os.getenv("NERVA_VERSION", "0.1.0"),
            "request_id": getattr(record, "request_id", "-"),
            "user_id": getattr(record, "user_id", "-"),
            "client_type": getattr(record, "client_type", "unknown"),
        }
        for name in (
            "event", "method", "route", "status_code", "elapsed_ms", "error_code",
            "provider", "model", "prompt_version", "prompt_tokens", "completion_tokens", "image_tokens",
            "client_version", "retrieval_mode", "fallback_reason", "candidate_count", "chunk_count",
            "keyword_candidate_count", "vector_candidate_count", "rerank_elapsed_ms",
            "document_id", "source_id", "session_id", "message_id",
        ):
            value = getattr(record, name, None)
            if value is not None:
                payload[name] = value
        if record.exc_info:
            payload["exception_type"] = record.exc_info[0].__name__
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def bind_request_context(request_id: str, client_type: str) -> tuple[contextvars.Token, contextvars.Token]:
    return request_id_var.set(request_id), client_type_var.set(client_type)


def bind_user_context(user_id: str) -> contextvars.Token:
    return user_id_var.set(user_id)


def clear_request_context(tokens: tuple[contextvars.Token, contextvars.Token]) -> None:
    try:
        request_id_var.reset(tokens[0])
    except ValueError:
        request_id_var.set("-")
    try:
        client_type_var.reset(tokens[1])
    except ValueError:
        client_type_var.set("unknown")
    user_id_var.set("-")


def current_request_id() -> str:
    return request_id_var.get()


def configure_logging() -> None:
    environment = os.getenv("NERVA_ENV", "development").strip().lower()
    level_name = os.getenv("NERVA_LOG_LEVEL", "INFO").strip().upper()
    level = getattr(logging, level_name, logging.INFO)
    use_json = os.getenv("NERVA_LOG_FORMAT", "text").strip().lower() == "json"
    formatter: logging.Formatter = JsonFormatter() if use_json else logging.Formatter(
        "%(asctime)s %(levelname)s %(name)s request_id=%(request_id)s "
        "user_id=%(user_id)s client=%(client_type)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    context_filter = ContextFilter()
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.addFilter(context_filter)
    handlers: list[logging.Handler] = [console]
    if environment != "production":
        log_dir = Path(os.getenv("NERVA_LOG_DIR") or DEFAULT_LOG_DIR)
        log_dir.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            log_dir / "nerva-api.log", maxBytes=10 * 1024 * 1024,
            backupCount=5, encoding="utf-8",
        )
        file_handler.setFormatter(formatter)
        file_handler.addFilter(context_filter)
        handlers.append(file_handler)
    logging.basicConfig(level=level, handlers=handlers, force=True)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)

    for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(logger_name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True


def configure_sentry() -> None:
    dsn = os.getenv("NERVA_SENTRY_DSN")
    if not dsn:
        return
    try:
        import sentry_sdk
    except ImportError:
        logging.getLogger("nerva.api").warning("sentry_sdk_unavailable")
        return

    def before_send(event, hint):
        safe = scrub_sensitive(event)
        request = safe.get("request") or {}
        if isinstance(request.get("url"), str):
            request["url"] = request["url"].split("?", 1)[0]
        exception = safe.get("exception") or {}
        for item in exception.get("values") or []:
            item["value"] = "Unhandled exception"
        for breadcrumb in safe.get("breadcrumbs", {}).get("values", []):
            data = breadcrumb.get("data") or {}
            if isinstance(data.get("url"), str):
                data["url"] = data["url"].split("?", 1)[0]
        return safe

    sentry_sdk.init(
        dsn=dsn,
        environment=os.getenv("NERVA_ENV", "development"),
        release=os.getenv("NERVA_VERSION", "0.1.0"),
        traces_sample_rate=float(os.getenv("NERVA_SENTRY_TRACES_SAMPLE_RATE", "0.1")),
        send_default_pii=False,
        before_send=before_send,
    )
