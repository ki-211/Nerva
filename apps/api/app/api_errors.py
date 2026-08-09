"""Stable, user-safe API error responses."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .logging_config import current_request_id
from .monitoring import metrics


STATUS_CODES = {
    400: "BAD_REQUEST", 401: "AUTH_REQUIRED", 403: "FORBIDDEN", 404: "NOT_FOUND",
    409: "CONFLICT", 413: "PAYLOAD_TOO_LARGE", 422: "VALIDATION_ERROR",
    429: "RATE_LIMITED", 500: "INTERNAL_ERROR", 503: "SERVICE_UNAVAILABLE",
}

STATUS_MESSAGES = {
    400: "请求无法处理", 401: "登录已失效，请重新登录", 403: "当前账号没有操作权限",
    404: "请求的内容不存在或已被移除", 409: "内容已更新，请刷新后重试",
    413: "上传内容过大", 422: "请求参数不符合要求", 429: "操作过于频繁，请稍后重试",
    500: "服务暂时不可用，请稍后重试", 503: "服务暂时不可用，请稍后重试",
}


def error_response(
    status_code: int, message: str, *, code: str | None = None,
    retryable: bool = False, request_id: str | None = None, extra: dict[str, Any] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {
        "code": code or STATUS_CODES.get(status_code, "REQUEST_FAILED"),
        "message": message,
        "retryable": retryable,
        "request_id": request_id or current_request_id(),
    }
    if extra:
        error.update(extra)
    return JSONResponse(
        status_code=status_code, content={"error": error},
        headers={"X-Request-ID": error["request_id"]},
    )


def _http_detail(exc: HTTPException) -> tuple[str, str, bool, dict[str, Any]]:
    detail = exc.detail
    if isinstance(detail, dict):
        message = str(detail.get("message") or "请求失败")
        code = str(detail.get("code") or STATUS_CODES.get(exc.status_code, "REQUEST_FAILED"))
        retryable = bool(detail.get("retryable", exc.status_code >= 500))
        allowed = {"source_id", "current_version", "requires_reupload"}
        extra = {key: detail[key] for key in allowed if key in detail}
        return message, code, retryable, extra
    raw = str(detail).strip() if isinstance(detail, str) else ""
    message = raw if raw and any("\u4e00" <= char <= "\u9fff" for char in raw) else STATUS_MESSAGES.get(
        exc.status_code, "操作失败，请稍后重试",
    )
    return message, STATUS_CODES.get(exc.status_code, "REQUEST_FAILED"), exc.status_code >= 500, {}


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(request: Request, exc: StarletteHTTPException):
        message, code, retryable, extra = _http_detail(exc)
        request.state.error_code = code
        metrics.increment("nerva_api_errors_total", code=code, status=exc.status_code)
        return error_response(exc.status_code, message, code=code, retryable=retryable, extra=extra)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_exception(request: Request, exc: RequestValidationError):
        request.state.error_code = "VALIDATION_ERROR"
        metrics.increment("nerva_api_errors_total", code="VALIDATION_ERROR", status=422)
        return error_response(422, "请求参数不符合要求", code="VALIDATION_ERROR")

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, exc: Exception):
        request.state.error_code = "INTERNAL_ERROR"
        import logging
        logging.getLogger("nerva.api").exception(
            "unhandled_request_error",
            extra={"event": "unhandled_request_error", "error_code": "INTERNAL_ERROR"},
        )
        metrics.increment("nerva_api_errors_total", code="INTERNAL_ERROR", status=500)
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(exc)
        except ImportError:
            pass
        return error_response(500, "服务暂时不可用，请稍后重试", code="INTERNAL_ERROR", retryable=True)
