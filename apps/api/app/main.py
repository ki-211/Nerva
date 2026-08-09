import secrets
import smtplib
import hashlib
import hmac
import ipaddress
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta
from pathlib import Path
from threading import Lock
from typing import Literal
from urllib.parse import quote

from fastapi import (
    BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Query, Request,
    Response, UploadFile, status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from starlette.background import BackgroundTask
from sqlalchemy import text

from .ai import (
    AIProviderError, SourceInput, build_planning_units, combine_extractions,
    get_ai_adapter, get_ocr_adapter, missing_proposal_refs,
    retrieve_candidates_balanced, validate_extraction,
)
from .auth import (
    authenticate_session, create_session, normalize_email, revoke_session,
    verification_code_hash, hash_password, verify_password,
)
from .mailer import send_registration_code
from .memories import (
    chat_memory_block, extract_memory_block, load_active_memories, normalize_memory_content,
    plan_memory_block,
)
from .chat import (
    ChatStreamParser, build_chat_history,
    retrieve_chat_sources, should_infer_memory, sse_event, validated_citations,
)
from .retrieval import HybridRetriever, rebuild_document_index
from .api_errors import error_response, register_error_handlers
from .logging_config import (
    bind_request_context, bind_user_context, clear_request_context,
    configure_logging, configure_sentry, current_request_id,
)
from .monitoring import metrics
from .image_ingestion import (
    ImageValidationError, TemporaryImage, cleanup_job_directory,
    cleanup_stale_directories, combine_ocr_text, image_data_url, save_uploads,
    split_ocr_text,
)
from .exports import (
    build_human_markdown_archive, build_knowledge_archive,
    render_single_markdown, safe_filename, single_markdown_filename,
)
from .prompts import EXTRACT_PROMPT_VERSION, MERGE_PROMPT_VERSION, OCR_PROMPT_VERSION
from .schemas import (
    ApplyChangeSet, ChangeSet, Document, DocumentUpdate, DocumentVersion,
    ChatMessage, ChatMessageCreate, ChatSession, ChatSessionCreate, ChatSessionUpdate,
    IngestionCreate, KnowledgeEvent, Memory, MemoryCreate, MemoryUpdate,
    ReindexResponse, ReprocessSource, SearchResponse, SourceProcessing,
    CodeLoginRequest, SendVerificationCodeRequest, User,
    AdminLoginRequest, AdminUser, KnowledgeOwnership, PublicDocumentCreate,
)
from .settings import settings
from .store import ChatSessionBusy, DocumentVersionConflict, Store, now_utc


configure_logging()
configure_sentry()
logger = logging.getLogger("nerva.api")
app = FastAPI(title="Nerva API", version=settings.service_version)
register_error_handlers(app)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = Store(settings.sqlalchemy_url(), create_schema=False)
ai = get_ai_adapter()
ocr = get_ocr_adapter()
index_executor: ThreadPoolExecutor | None = None
index_executor_lock = Lock()


def _get_index_executor() -> ThreadPoolExecutor:
    global index_executor
    with index_executor_lock:
        if index_executor is None:
            index_executor = ThreadPoolExecutor(
                max_workers=settings.index_worker_count, thread_name_prefix="nerva-index",
            )
        return index_executor


def _safe_client_type(value: str | None) -> str:
    return value if value in {"user-desktop", "admin-desktop", "web-development"} else "unknown"


def _safe_request_id(value: str | None) -> str:
    if value and 1 <= len(value) <= 64 and all(char.isalnum() or char in "-_." for char in value):
        return value
    return secrets.token_hex(16)


def _admin_login_fingerprints(request: Request, username: str) -> tuple[str, str]:
    address = request.client.host if request.client else "unknown"
    secret = settings.verification_code_secret.encode("utf-8")
    account = hmac.new(secret, username.strip().casefold().encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    ip_address = hmac.new(secret, address.encode("utf-8"), hashlib.sha256).hexdigest()[:32]
    return f"account:{account}", f"ip:{ip_address}"


def _audit(
    request: Request, actor: dict | None, action: str, target_type: str,
    target_id: str | None, outcome: str,
) -> None:
    try:
        store.record_audit_event(
            actor_user_id=actor.get("id") if actor else None,
            actor_role=actor.get("role", "anonymous") if actor else "anonymous",
            action=action, target_type=target_type, target_id=target_id,
            outcome=outcome, request_id=request.state.request_id,
            client_type=request.state.client_type,
        )
    except Exception:
        logger.exception("audit_event_write_failed", extra={"event": "audit_event_write_failed"})


def _run_index_rebuild(
    user_id: str, document_id: str, request_id: str, client_type: str, trigger: str,
) -> None:
    tokens = bind_request_context(request_id, client_type)
    user_token = bind_user_context(user_id)
    metrics.adjust_gauge("nerva_index_jobs_active", 1)
    try:
        rebuild_document_index(store, user_id, document_id, ai)
    except Exception:
        metrics.increment("nerva_index_jobs_total", status="failed", trigger=trigger)
        logger.exception(
            "document_index_job_failed",
            extra={
                "event": "document_index_job_failed", "error_code": "INDEX_JOB_FAILED",
                "document_id": document_id,
            },
        )
    else:
        metrics.increment("nerva_index_jobs_total", status="completed", trigger=trigger)
    finally:
        metrics.adjust_gauge("nerva_index_jobs_active", -1)
        try:
            from .logging_config import user_id_var
            user_id_var.reset(user_token)
        except (ValueError, RuntimeError):
            pass
        clear_request_context(tokens)


def submit_index_rebuild(
    user_id: str, document_id: str, *, request_id: str | None = None,
    client_type: str = "unknown", trigger: str,
) -> None:
    metrics.increment("nerva_index_jobs_submitted_total", trigger=trigger)
    _get_index_executor().submit(
        _run_index_rebuild, user_id, document_id,
        request_id or current_request_id(), client_type, trigger,
    )


@app.middleware("http")
async def reject_untrusted_origins(request: Request, call_next):
    request_id = _safe_request_id(request.headers.get("X-Request-ID"))
    client_type = _safe_client_type(request.headers.get("X-Nerva-Client"))
    client_version = (request.headers.get("X-Nerva-Version") or "unknown")[:64]
    request.state.request_id = request_id
    request.state.client_type = client_type
    request.state.client_version = client_version
    tokens = bind_request_context(request_id, client_type)
    started = time.perf_counter()
    response = None
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and origin not in settings.cors_origins:
            request.state.error_code = "UNTRUSTED_ORIGIN"
            response = error_response(403, "请求来源不受信任", code="UNTRUSTED_ORIGIN")
    try:
        if response is None:
            response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
    except Exception as exc:
        request.state.error_code = "INTERNAL_ERROR"
        metrics.increment("nerva_api_errors_total", code="INTERNAL_ERROR", status=500)
        logger.exception(
            "unhandled_request_error",
            extra={"event": "unhandled_request_error", "error_code": "INTERNAL_ERROR"},
        )
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(exc)
        except ImportError:
            pass
        response = error_response(
            500, "服务暂时不可用，请稍后重试", code="INTERNAL_ERROR",
            retryable=True, request_id=request_id,
        )
        return response
    finally:
        route = getattr(request.scope.get("route"), "path", request.url.path)
        status_code = response.status_code if response is not None else 500
        elapsed = time.perf_counter() - started
        metrics.observe_request(request.method, route, status_code, elapsed)
        if getattr(request.state, "user_id", None):
            bind_user_context(request.state.user_id)
        logger.info(
            "request_completed",
            extra={
                "event": "request_completed", "method": request.method, "route": route,
                "status_code": status_code, "elapsed_ms": int(elapsed * 1000),
                "error_code": getattr(request.state, "error_code", None),
                "client_version": client_version,
            },
        )
        clear_request_context(tokens)


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=settings.session_cookie_name,
        value=token,
        max_age=settings.session_days * 24 * 60 * 60,
        httponly=True,
        secure=settings.session_cookie_secure,
        samesite="lax",
        path="/",
    )


def current_user(request: Request) -> dict:
    user = authenticate_session(store, request.cookies.get(settings.session_cookie_name))
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "请先登录")
    request.state.user_id = user["id"]
    request.state.user_role = user.get("role", "user")
    bind_user_context(user["id"])
    return user


def admin_user(request: Request, user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "admin":
        _audit(request, user, "admin.access", "admin_api", request.url.path, "denied")
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail={
            "message": "需要管理员权限", "code": "ADMIN_REQUIRED",
        })
    return user


def _validate_export_scope(
    scope: Literal["library", "document"], document_id: str | None,
    version: int | None = None,
) -> None:
    if scope == "document" and not document_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "document scope requires document_id")
    if scope == "library" and (document_id is not None or version is not None):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "library scope does not accept document_id or version")


def _attachment_header(filename: str) -> str:
    fallback = safe_filename(filename.encode("ascii", "ignore").decode() or "nerva-export")
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename)}"


@app.on_event("startup")
def recover_interrupted_image_work() -> None:
    settings.validate()
    configured_hash = hash_password(settings.admin_password)
    existing = store.get_user_by_username(settings.admin_username)
    password_matches = bool(existing and verify_password(settings.admin_password, existing.get("password_hash")))
    password_changed = store.ensure_admin(
        username=settings.admin_username,
        email=settings.admin_email,
        password_hash=configured_hash,
        password_matches=password_matches,
    )
    if password_changed:
        logger.info("administrator_account_synchronized password_changed=true")
        synchronized_admin = store.get_user_by_username(settings.admin_username)
        if synchronized_admin:
            try:
                for action in ("admin.credentials.sync", "admin.sessions.revoke"):
                    store.record_audit_event(
                        actor_user_id=synchronized_admin["id"], actor_role="system",
                        action=action, target_type="user", target_id=synchronized_admin["id"],
                        outcome="success", request_id="startup", client_type="system",
                    )
            except Exception:
                logger.exception("administrator_startup_audit_failed")
    removed = cleanup_stale_directories()
    interrupted = store.fail_interrupted_image_sources()
    interrupted_chats = store.fail_interrupted_chat_messages()
    if removed or interrupted or interrupted_chats:
        logger.warning(
            "startup recovery removed_temp_dirs=%s interrupted_sources=%s interrupted_chats=%s",
            removed, interrupted, interrupted_chats,
        )
    cutoff = now_utc() - timedelta(minutes=settings.index_recovery_age_minutes)
    for pending in store.list_pending_index_documents(
        older_than=cutoff, limit=settings.index_recovery_limit,
    ):
        submit_index_rebuild(
            pending["user_id"], pending["document_id"], request_id="startup-recovery",
            client_type="system", trigger="startup_recovery",
        )


@app.on_event("shutdown")
def shutdown_background_workers() -> None:
    global index_executor
    with index_executor_lock:
        current = index_executor
        index_executor = None
    if current:
        current.shutdown(wait=False, cancel_futures=True)


def source_processing_payload(source: dict) -> dict:
    error = None
    if source.get("error_code"):
        error_code = source["error_code"]
        requires_reupload = source.get("kind") == "image" and (
            error_code.startswith(("OCR_", "IMAGE_")) or error_code == "WORKER_INTERRUPTED"
        )
        if error_code.startswith("AI_"):
            safe_message = "AI 服务处理失败，请稍后重试"
        elif error_code.startswith(("OCR_", "IMAGE_")):
            safe_message = "图片处理失败，请重新上传"
        elif error_code == "WORKER_INTERRUPTED":
            safe_message = "处理已中断，请重新上传"
        else:
            safe_message = "知识处理失败，请稍后重试"
        error = {
            "code": error_code,
            "message": safe_message,
            "retryable": not requires_reupload,
            "requires_reupload": requires_reupload,
        }
    return {
        "source_id": source["id"],
        "status": source["processing_status"],
        "stage": source["processing_stage"],
        "processed_inputs": source["processed_inputs"],
        "total_inputs": source["total_inputs"],
        "covered_inputs": source.get("covered_inputs", 0),
        "input_coverage": source.get("input_coverage", []),
        "extraction_attempts": source.get("extraction_attempts", 0),
        "change_set_id": source.get("change_set_id"),
        "error": error,
    }


@app.get("/health")
def health():
    return {"status": "ok", "version": app.version, "ai_provider": settings.ai_provider}


@app.get("/health/live")
def health_live():
    return {"status": "live", "version": app.version}


@app.get("/health/ready")
def health_ready():
    try:
        settings.validate()
        with store.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        if revision != "0012":
            return error_response(
                503, "服务正在等待数据库升级", code="DATABASE_MIGRATION_PENDING", retryable=True,
            )
    except Exception:
        logger.exception("readiness_check_failed", extra={"event": "readiness_check_failed"})
        return error_response(503, "服务尚未就绪", code="SERVICE_NOT_READY", retryable=True)
    return {"status": "ready", "version": app.version, "database_revision": revision}


@app.get("/metrics")
def prometheus_metrics(request: Request):
    if settings.environment == "production":
        try:
            client_address = ipaddress.ip_address(request.client.host if request.client else "")
        except ValueError:
            client_address = None
        allowed = client_address is not None and any(
            client_address in ipaddress.ip_network(network, strict=False)
            for network in settings.metrics_allowed_networks
        )
        if not allowed:
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail={
                "message": "监控来源不受信任", "code": "METRICS_NETWORK_FORBIDDEN",
            })
    if settings.metrics_token:
        expected = f"Bearer {settings.metrics_token}"
        if not secrets.compare_digest(request.headers.get("Authorization", ""), expected):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail={
                "message": "监控凭据无效", "code": "METRICS_FORBIDDEN",
            })
    for chunk_status, count in store.count_chunks_by_status().items():
        metrics.gauge("nerva_document_chunks", count, status=chunk_status)
    pool = store.engine.pool
    if hasattr(pool, "checkedout"):
        checked_out = pool.checkedout()
        size = pool.size() if hasattr(pool, "size") else 0
        max_overflow = max(0, int(getattr(pool, "_max_overflow", 0)))
        capacity = max(1, size + max_overflow)
        metrics.gauge("nerva_database_pool_checked_out", checked_out)
        metrics.gauge("nerva_database_pool_capacity", capacity)
        metrics.gauge("nerva_database_pool_utilization_ratio", checked_out / capacity)
    return Response(content=metrics.render(), media_type="text/plain; version=0.0.4")


@app.post("/v1/auth/code-login", response_model=User)
def code_login(payload: CodeLoginRequest, response: Response):
    email = normalize_email(str(payload.email))
    if not store.consume_verification_code(
        email, verification_code_hash(email, payload.verification_code), now_utc()
    ):
        metrics.increment("nerva_verification_code_total", outcome="failure")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "验证码错误或已过期")
    user = store.get_user_by_email(email)
    if user and user["status"] != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已停用")
    if user and user.get("role") == "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "管理员请使用管理员登录")
    if not user:
        user = store.create_user(email, email.split("@", 1)[0][:80])
    set_session_cookie(response, create_session(store, user["id"]))
    metrics.increment("nerva_verification_code_total", outcome="success")
    return user


@app.post("/v1/auth/admin-login", response_model=User)
def admin_login(payload: AdminLoginRequest, request: Request, response: Response):
    username = payload.username.strip()
    account_fingerprint, ip_fingerprint = _admin_login_fingerprints(request, username)
    since = now_utc() - timedelta(minutes=settings.admin_login_window_minutes)
    locked_target = next((target for target in (account_fingerprint, ip_fingerprint) if
        store.count_recent_audit_events(
            action="admin.login", target_id=target, outcomes=("failure", "locked"), since=since,
        ) >= settings.admin_login_max_failures
    ), None)
    if locked_target:
        _audit(request, None, "admin.login", "login_fingerprint", locked_target, "locked")
        metrics.increment("nerva_admin_login_total", outcome="locked")
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail={
            "message": "管理员登录尝试过于频繁，请稍后再试",
            "code": "ADMIN_LOGIN_LOCKED",
            "retryable": True,
        })
    user = store.get_user_by_username(username)
    if (
        not user
        or user.get("role") != "admin"
        or user.get("status") != "active"
        or not verify_password(payload.password, user.get("password_hash"))
    ):
        _audit(request, None, "admin.login", "account_fingerprint", account_fingerprint, "failure")
        _audit(request, None, "admin.login", "ip_fingerprint", ip_fingerprint, "failure")
        metrics.increment("nerva_admin_login_total", outcome="failure")
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail={
            "message": "管理员账号或密码错误", "code": "ADMIN_LOGIN_FAILED",
        })
    set_session_cookie(response, create_session(store, user["id"]))
    _audit(request, user, "admin.login", "user", user["id"], "success")
    metrics.increment("nerva_admin_login_total", outcome="success")
    return user


@app.post("/v1/auth/verification-codes", status_code=204)
def send_verification_code(payload: SendVerificationCodeRequest, response: Response):
    email = normalize_email(str(payload.email))
    now = now_utc()
    if store.verification_code_is_cooling_down(email, now):
        metrics.increment("nerva_verification_code_total", outcome="rate_limited")
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "发送太频繁，请 60 秒后再试")
    code = f"{secrets.randbelow(1_000_000):06d}"
    try:
        send_registration_code(email, code)
    except (RuntimeError, OSError, smtplib.SMTPException):
        logger.exception(
            "verification email delivery failed smtp_host=%s smtp_port=%s ssl=%s",
            settings.smtp_host or "<missing>", settings.smtp_port, settings.smtp_use_ssl,
        )
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "验证码发送失败，请稍后重试")
    logger.info(
        "verification email delivered smtp_host=%s smtp_port=%s",
        settings.smtp_host, settings.smtp_port,
    )
    store.save_verification_code(
        email=email,
        code_hash=verification_code_hash(email, code),
        expires_at=now + timedelta(minutes=5),
        resend_after=now + timedelta(seconds=60),
    )
    response.status_code = status.HTTP_204_NO_CONTENT
    return None


@app.post("/v1/auth/logout", status_code=204)
def logout(request: Request, response: Response, user: dict = Depends(current_user)):
    revoke_session(store, request.cookies.get(settings.session_cookie_name))
    if user.get("role") == "admin":
        _audit(request, user, "admin.session.revoke", "session", None, "success")
    response.delete_cookie(settings.session_cookie_name, path="/", samesite="lax")
    response.status_code = status.HTTP_204_NO_CONTENT
    return None


@app.get("/v1/auth/me", response_model=User)
def me(user: dict = Depends(current_user)):
    return user


@app.post("/v1/ingestions", response_model=ChangeSet, status_code=201)
def create_ingestion(payload: IngestionCreate, user: dict = Depends(current_user)):
    source = store.create_source(user["id"], payload.kind, payload.content, payload.title)
    return process_source(user["id"], source["id"])


def process_source(user_id: str, source_id: str):
    source = store.claim_source_for_processing(
        user_id, source_id, provider=ai.provider, model=ai.model,
        prompt_version=f"{EXTRACT_PROMPT_VERSION}+{MERGE_PROMPT_VERSION}",
    )
    if not source:
        raise HTTPException(status.HTTP_409_CONFLICT, "Source is not available for processing")
    return run_knowledge_pipeline(user_id, source_id)


def _try_infer_and_store_memories(ai, store, user_id: str, instruction: str, source_label: str | None):
    """Infer user preferences from reprocess instruction and store as candidates.

    Non-fatal: if inference fails, logs and continues without raising.
    Deduplicates against all existing memories by normalized kind+content.
    """
    try:
        result = ai.infer_preferences(
            analysis_instruction=instruction,
            source_label=source_label,
        )
        if not result.memories:
            return []

        existing_memories = store.list_memories(user_id)
        existing_keys = {
            (m["kind"], normalize_memory_content(m["content"]))
            for m in existing_memories
        }

        created = []
        for inferred in result.memories:
            content = inferred.content.strip()
            key = (inferred.kind, normalize_memory_content(content))
            if key in existing_keys:
                continue
            memory = store.create_memory(
                user_id,
                kind=inferred.kind,
                content=content,
                scope="global",
                scope_ref=None,
                status="candidate",
                confidence=inferred.confidence,
                origin="ai_inferred",
            )
            created.append(memory)
            existing_keys.add(key)
            logger.info(
                "memory_inferred user_id=%s kind=%s confidence=%.2f",
                user_id, inferred.kind, inferred.confidence,
            )
        return created
    except Exception:
        logger.warning("memory_inference_failed user_id=%s", user_id)
        return []


def run_knowledge_pipeline(user_id: str, source_id: str):
    source = store.get_source(user_id, source_id)
    if not source or source["processing_status"] != "processing":
        raise HTTPException(status.HTTP_409_CONFLICT, "Source is not available for processing")
    try:
        # Load user preferences once upfront for both pipeline stages
        active_memories = load_active_memories(store, user_id)
        extract_prefs = extract_memory_block(active_memories)
        plan_prefs = plan_memory_block(active_memories)
        # Track which memories were used so we can increment use_count at the end
        used_memory_ids = [m["id"] for m in active_memories if m["status"] == "active"]

        if source["kind"] == "image":
            source_context, persisted_inputs = split_ocr_text(
                source["content"], source["total_inputs"],
            )
            inputs = [
                SourceInput(input_index=index, content=content)
                for index, content in persisted_inputs
            ]
        else:
            source_context = None
            inputs = [SourceInput(input_index=0, content=source["content"].strip())]
        instruction = source.get("pending_analysis_instruction")

        store.update_source_stage(user_id, source_id, "extracting")
        initial = ai.extract_inputs(
            inputs, source["title"], source_context=source_context,
            analysis_instruction=instruction, memory_block=extract_prefs,
        )
        extraction, missing_inputs = validate_extraction(initial, inputs)
        attempts = 1
        covered = len(inputs) - len(missing_inputs)
        stored_covered = covered if source["kind"] == "image" else 0
        if missing_inputs:
            store.update_extraction_progress(
                user_id, source_id, covered_inputs=stored_covered,
                extraction_attempts=attempts, stage="coverage_repair",
            )
            missing_set = set(missing_inputs)
            repair_inputs = [item for item in inputs if item.input_index in missing_set]
            repaired_raw = ai.extract_inputs(
                repair_inputs, source["title"], source_context=source_context,
                analysis_instruction=instruction, memory_block=extract_prefs, repair=True,
            )
            repaired, _ = validate_extraction(repaired_raw, repair_inputs)
            extraction = combine_extractions(extraction, repaired)
            extraction, missing_inputs = validate_extraction(extraction, inputs)
            attempts = 2
            covered = len(inputs) - len(missing_inputs)
            stored_covered = covered if source["kind"] == "image" else 0
        if missing_inputs:
            raise AIProviderError(
                "AI_INCOMPLETE_COVERAGE",
                f"仍有 {len(missing_inputs)} 个输入未提取到可验证知识",
                retryable=True,
            )
        store.update_extraction_progress(
            user_id, source_id, covered_inputs=stored_covered,
            extraction_attempts=attempts, stage="retrieving",
        )
        logger.info(
            "knowledge_coverage source_id=%s covered_inputs=%s total_inputs=%s extraction_attempts=%s",
            source_id, covered, len(inputs), attempts,
        )
        store.update_source_stage(user_id, source_id, "retrieving")
        documents_by_id = {item["id"]: item for item in store.list_documents(user_id)}
        candidates: list[dict] = []
        seen_candidate_ids: set[str] = set()
        for input_item in inputs:
            retrieval = HybridRetriever(store, ai).retrieve(
                user_id, input_item.content, [source.get("title") or ""], final_count=8,
            )
            for chunk in retrieval.results:
                document = documents_by_id.get(chunk["document_id"])
                if document and document["id"] not in seen_candidate_ids:
                    candidates.append(document)
                    seen_candidate_ids.add(document["id"])
        if not candidates:
            candidates = retrieve_candidates_balanced(
                inputs, source["title"], list(documents_by_id.values()), limit=8,
            )
        store.update_source_stage(user_id, source_id, "planning")
        planning_units = build_planning_units(extraction)
        proposals = ai.plan_units(
            planning_units, candidates, source["title"],
            analysis_instruction=instruction, memory_block=plan_prefs,
        )
        missing_refs = missing_proposal_refs(proposals, planning_units)
        if missing_refs:
            missing_ref_set = set(missing_refs)
            repair_units = [unit for unit in planning_units if unit.ref in missing_ref_set]
            proposals.extend(ai.plan_units(
                repair_units, candidates, source["title"],
                analysis_instruction=instruction, memory_block=plan_prefs, repair=True,
            ))
            missing_refs = missing_proposal_refs(proposals, planning_units)
        if missing_refs:
            raise AIProviderError(
                "AI_INCOMPLETE_PLAN",
                f"仍有 {len(missing_refs)} 个知识单元未进入变更草案",
                retryable=True,
            )
        change_set = store.create_change_set_for_source(
            user_id, source_id, proposals, extraction=extraction,
            supersedes_change_set_id=source.get("pending_supersedes_change_set_id"),
            analysis_instruction=instruction,
            covered_inputs=covered if source["kind"] == "image" else 0,
            extraction_attempts=attempts,
        )

        try:
            store.increment_memory_usage(user_id, used_memory_ids)
        except Exception:
            logger.warning(
                "memory_usage_update_failed user_id=%s source_id=%s",
                user_id, source_id,
            )

        # After a successful reprocess with an analysis_instruction, ask the AI to
        # infer stable user preferences and write them as candidate memories for review.
        if instruction and hasattr(ai, "infer_preferences"):
            _try_infer_and_store_memories(ai, store, user_id, instruction, source["title"])

        return change_set
    except ImageValidationError as exc:
        store.mark_source_failed(user_id, source_id, exc.code, str(exc))
        logger.warning("source input parsing failed source_id=%s error_code=%s", source_id, exc.code)
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail={
            "message": str(exc), "code": exc.code, "source_id": source_id,
            "retryable": False,
        }) from exc
    except AIProviderError as exc:
        metrics.increment("nerva_model_calls_total", operation="ai", status="failed")
        store.mark_source_failed(user_id, source_id, exc.code, "AI 服务处理失败，请稍后重试")
        logger.warning(
            "source processing failed source_id=%s provider=%s model=%s error_code=%s retryable=%s "
            "upstream_status=%s upstream_code=%s provider_request_id=%s",
            source_id, ai.provider, ai.model, exc.code, exc.retryable,
            exc.upstream_status, exc.upstream_code, exc.request_id,
        )
        raise HTTPException(exc.status_code, detail={
            "message": "AI 服务处理失败，请稍后重试", "code": exc.code, "source_id": source_id,
            "retryable": exc.retryable,
        }) from exc
    except Exception as exc:
        store.mark_source_failed(user_id, source_id, "PROCESSING_ERROR", "知识处理失败，请稍后重试")
        logger.exception(
            "source processing failed source_id=%s provider=%s model=%s error_code=PROCESSING_ERROR",
            source_id, ai.provider, ai.model,
        )
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail={
            "message": "知识处理失败，请稍后重试", "code": "PROCESSING_ERROR",
            "source_id": source_id, "retryable": True,
        }) from exc


def process_source_background(user_id: str, source_id: str) -> None:
    metrics.adjust_gauge("nerva_image_tasks_active", 1)
    try:
        process_source(user_id, source_id)
    except HTTPException:
        metrics.increment("nerva_image_tasks_total", status="failed")
    else:
        metrics.increment("nerva_image_tasks_total", status="completed")
    finally:
        metrics.adjust_gauge("nerva_image_tasks_active", -1)


def _recognize_temporary_image(source_id: str, image: TemporaryImage) -> tuple[int, str]:
    try:
        result = ocr.recognize(
            image_data_url(image), source_id=source_id, sequence=image.sequence,
        )
        return image.sequence, result.text
    finally:
        try:
            image.path.unlink(missing_ok=True)
        except OSError:
            logger.warning(
                "temporary image cleanup failed source_id=%s sequence=%s",
                source_id, image.sequence,
            )


def process_image_source(
    user_id: str, source_id: str, note: str | None,
    job_directory: Path, images: list[TemporaryImage],
) -> None:
    if not store.start_image_ocr(user_id, source_id):
        cleanup_job_directory(job_directory)
        return
    try:
        ordered: dict[int, str] = {}
        first_error: Exception | None = None
        with ThreadPoolExecutor(max_workers=min(3, len(images))) as executor:
            futures = {
                executor.submit(_recognize_temporary_image, source_id, image): image.sequence
                for image in images
            }
            for future in as_completed(futures):
                try:
                    sequence, text = future.result()
                    ordered[sequence] = text
                    store.increment_processed_inputs(user_id, source_id)
                except Exception as exc:
                    if first_error is None:
                        first_error = exc
        if first_error:
            raise first_error
        combined = combine_ocr_text(note, [ordered[index] for index in range(1, len(images) + 1)])
        store.save_ocr_content(user_id, source_id, combined)
        run_knowledge_pipeline(user_id, source_id)
    except AIProviderError as exc:
        metrics.increment(
            "nerva_model_calls_total",
            operation="ocr" if exc.code.startswith("OCR_") else "ai", status="failed",
        )
        store.mark_source_failed(user_id, source_id, exc.code, "图片识别失败，请稍后重试")
        logger.warning(
            "image processing failed source_id=%s model=%s error_code=%s "
            "upstream_status=%s upstream_code=%s provider_request_id=%s",
            source_id, ocr.model, exc.code, exc.upstream_status,
            exc.upstream_code, exc.request_id,
        )
    except ImageValidationError as exc:
        store.mark_source_failed(user_id, source_id, exc.code, str(exc))
        logger.warning("image processing failed source_id=%s error_code=%s", source_id, exc.code)
    except HTTPException:
        # The knowledge pipeline already persisted and logged its stable failure.
        return
    except Exception:
        store.mark_source_failed(user_id, source_id, "IMAGE_PROCESSING_ERROR", "图片处理失败，请重新上传")
        logger.exception("image processing failed source_id=%s error_code=IMAGE_PROCESSING_ERROR", source_id)
    finally:
        cleanup_job_directory(job_directory)


@app.post("/v1/image-ingestions", response_model=SourceProcessing, status_code=202)
async def create_image_ingestion(
    background_tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    title: str | None = Form(default=None),
    note: str | None = Form(default=None),
    user: dict = Depends(current_user),
):
    normalized_title = (title or "").strip() or None
    normalized_note = (note or "").strip() or None
    if normalized_title and len(normalized_title) > 160:
        raise HTTPException(422, "标题不能超过 160 个字符")
    if normalized_note and len(normalized_note) > 20_000:
        raise HTTPException(422, "补充说明不能超过 20,000 个字符")
    try:
        job_directory, images = await save_uploads(files)
    except ImageValidationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail={
            "message": str(exc), "code": exc.code,
            "retryable": False, "requires_reupload": True,
        }) from exc
    try:
        source = store.create_image_source(
            user["id"], title=normalized_title,
            total_inputs=len(images), ocr_model=ocr.model,
            ocr_prompt_version=OCR_PROMPT_VERSION,
        )
    except Exception:
        cleanup_job_directory(job_directory)
        raise
    background_tasks.add_task(
        process_image_source, user["id"], source["id"], normalized_note,
        job_directory, images,
    )
    processing = store.get_source_processing(user["id"], source["id"])
    assert processing is not None
    return source_processing_payload(processing)


@app.get("/v1/sources/{source_id}/processing", response_model=SourceProcessing)
def get_source_processing(source_id: str, user: dict = Depends(current_user)):
    source = store.get_source_processing(user["id"], source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    return source_processing_payload(source)


@app.post("/v1/sources/{source_id}/reprocess", response_model=SourceProcessing, status_code=202)
def reprocess_source(
    source_id: str, payload: ReprocessSource, background_tasks: BackgroundTasks,
    user: dict = Depends(current_user),
):
    source = store.get_source(user["id"], source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    if source["processing_status"] in {"received", "processing"}:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "message": "来源正在处理中", "code": "SOURCE_ALREADY_PROCESSING",
            "source_id": source_id, "retryable": False,
        })
    if source["kind"] == "image" and (
        not source["content"].strip() or source["processed_inputs"] < source["total_inputs"]
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "message": "OCR 尚未完整保存，原图片已删除，请重新上传",
            "code": "IMAGE_REUPLOAD_REQUIRED", "source_id": source_id,
            "retryable": False, "requires_reupload": True,
        })
    processing = store.get_source_processing(user["id"], source_id)
    draft = (
        store.get_change_set(user["id"], processing["change_set_id"])
        if processing and processing.get("change_set_id") else None
    )
    if not draft:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "message": "该来源还没有可重新分析的草案", "code": "SOURCE_DRAFT_REQUIRED",
            "source_id": source_id, "retryable": False,
        })
    if draft["status"] != "proposed":
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "message": "已审批的来源不能重新分析", "code": "SOURCE_ALREADY_APPLIED",
            "source_id": source_id, "retryable": False,
        })
    queued = store.queue_source_reprocess(
        user["id"], source_id, draft["id"], payload.instruction,
    )
    if not queued:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "message": "来源当前不能重新分析", "code": "SOURCE_REPROCESS_CONFLICT",
            "source_id": source_id, "retryable": True,
        })
    background_tasks.add_task(process_source_background, user["id"], source_id)
    return source_processing_payload(queued)


@app.post("/v1/sources/{source_id}/retry", response_model=ChangeSet | SourceProcessing)
def retry_source(
    source_id: str, background_tasks: BackgroundTasks,
    response: Response, user: dict = Depends(current_user),
):
    source = store.get_source(user["id"], source_id)
    if not source:
        raise HTTPException(404, "Source not found")
    if source["processing_status"] != "failed":
        raise HTTPException(status.HTTP_409_CONFLICT, "Only failed sources can be retried")
    if source["kind"] == "image":
        requires_reupload = (
            (source.get("error_code") or "").startswith(("OCR_", "IMAGE_"))
            or source.get("error_code") == "WORKER_INTERRUPTED"
        )
        if requires_reupload:
            raise HTTPException(status.HTTP_409_CONFLICT, detail={
                "message": "原图片已按隐私策略删除，请重新选择图片上传",
                "code": "IMAGE_REUPLOAD_REQUIRED", "source_id": source_id,
                "retryable": False, "requires_reupload": True,
            })
        queued = store.queue_source_retry(user["id"], source_id)
        if not queued:
            raise HTTPException(status.HTTP_409_CONFLICT, "Source is not available for retry")
        background_tasks.add_task(process_source_background, user["id"], source_id)
        response.status_code = status.HTTP_202_ACCEPTED
        return source_processing_payload(queued)
    return process_source(user["id"], source_id)


@app.get("/v1/change-sets/{change_set_id}", response_model=ChangeSet)
def get_change_set(change_set_id: str, user: dict = Depends(current_user)):
    result = store.get_change_set(user["id"], change_set_id)
    if not result:
        raise HTTPException(404, "Change set not found")
    return result


@app.post("/v1/change-sets/{change_set_id}/apply", response_model=ChangeSet)
def apply_change_set(change_set_id: str, payload: ApplyChangeSet, user: dict = Depends(current_user)):
    result = store.apply_change_set(user["id"], change_set_id, payload.accepted_item_ids)
    if not result:
        raise HTTPException(404, "Change set not found or is no longer applicable")
    for item in result.get("items", []):
        if (
            item.get("accepted") and item.get("target_document_id")
            and item.get("operation") in {"CREATE_DOCUMENT", "ADD_BLOCK"}
        ):
            submit_index_rebuild(
                user["id"], item["target_document_id"],
                client_type="user-desktop", trigger="change_set_apply",
            )
    return result


@app.get("/v1/documents", response_model=list[Document])
def list_documents(user: dict = Depends(current_user)):
    return store.list_documents(user["id"])


@app.get("/v1/public-documents", response_model=list[Document])
def list_public_documents(user: dict = Depends(current_user)):
    return store.list_public_documents()


@app.get("/v1/public-documents/{document_id}", response_model=Document)
def get_public_document(document_id: str, user: dict = Depends(current_user)):
    result = store.get_document(user["id"], document_id)
    if not result or result.get("visibility") != "public":
        raise HTTPException(404, "Public document not found")
    return result


@app.get("/v1/admin/users", response_model=list[AdminUser])
def admin_users(request: Request, user: dict = Depends(admin_user)):
    result = store.list_users()
    _audit(request, user, "admin.users.list", "user_collection", None, "success")
    return result


@app.get("/v1/admin/knowledge-ownership", response_model=list[KnowledgeOwnership])
def admin_knowledge_ownership(request: Request, user: dict = Depends(admin_user)):
    result = store.list_knowledge_ownership()
    _audit(request, user, "admin.knowledge.list", "document_collection", None, "success")
    return result


@app.get("/v1/admin/documents/{document_id}", response_model=Document)
def admin_document_detail(
    document_id: str, request: Request, user: dict = Depends(admin_user),
):
    _audit(request, user, "admin.private_document.read", "document", document_id, "denied")
    raise HTTPException(status.HTTP_403_FORBIDDEN, detail={
        "message": "管理员无权读取普通用户的私有文档正文",
        "code": "ADMIN_PRIVATE_CONTENT_FORBIDDEN",
    })


@app.get("/v1/admin/public-documents", response_model=list[Document])
def admin_public_documents(request: Request, user: dict = Depends(admin_user)):
    _audit(request, user, "admin.public_document.list", "public_document_collection", None, "success")
    return store.list_public_documents()


@app.post("/v1/admin/public-documents", response_model=Document, status_code=201)
def create_admin_public_document(
    payload: PublicDocumentCreate, request: Request, user: dict = Depends(admin_user),
):
    result = store.create_public_document(user["id"], title=payload.title, markdown=payload.markdown)
    submit_index_rebuild(
        user["id"], result["id"], request_id=request.state.request_id,
        client_type=request.state.client_type, trigger="public_document_create",
    )
    _audit(request, user, "admin.public_document.create", "document", result["id"], "success")
    return result


@app.put("/v1/admin/public-documents/{document_id}", response_model=Document)
def update_admin_public_document(
    document_id: str, payload: DocumentUpdate, request: Request,
    user: dict = Depends(admin_user),
):
    current = store.get_owned_document(user["id"], document_id)
    if not current or current.get("visibility") != "public":
        raise HTTPException(404, "Public document not found")
    try:
        result = store.update_document(
            user["id"], document_id, title=payload.title, markdown=payload.markdown,
            base_version=payload.base_version, reason=payload.reason,
        )
    except DocumentVersionConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "message": "公共文档已在其他位置更新，请载入最新版本后再保存",
            "code": "DOCUMENT_VERSION_CONFLICT", "current_version": exc.current_version,
        }) from exc
    if not result:
        raise HTTPException(404, "Public document not found")
    if result["version"] != payload.base_version:
        submit_index_rebuild(
            user["id"], document_id, request_id=request.state.request_id,
            client_type=request.state.client_type, trigger="public_document_update",
        )
    _audit(request, user, "admin.public_document.update", "document", document_id, "success")
    return result


@app.delete("/v1/admin/public-documents/{document_id}", response_model=Document)
def unpublish_admin_public_document(
    document_id: str, request: Request, user: dict = Depends(admin_user),
):
    current = store.get_owned_document(user["id"], document_id)
    if not current or current.get("visibility") != "public":
        raise HTTPException(404, "Public document not found")
    result = store.set_document_visibility(user["id"], document_id, "private")
    if not result:
        raise HTTPException(404, "Public document not found")
    _audit(request, user, "admin.public_document.unpublish", "document", document_id, "success")
    return result


@app.get("/v1/exports/markdown")
def export_markdown(
    scope: Literal["library", "document"],
    document_id: str | None = None,
    version: int | None = Query(default=None, ge=1),
    user: dict = Depends(current_user),
):
    _validate_export_scope(scope, document_id, version)
    started = time.perf_counter()
    documents_snapshot = store.export_documents_snapshot(
        user["id"], document_id=document_id, version=version,
    )
    if documents_snapshot is None:
        raise HTTPException(404, "Document or version not found")
    if scope == "document":
        document = documents_snapshot[0]
        logger.info(
            "knowledge_export audience=human scope=document documents=1 elapsed_ms=%s",
            round((time.perf_counter() - started) * 1000),
        )
        filename = single_markdown_filename(document)
        return Response(
            content=render_single_markdown(document), media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": _attachment_header(filename)},
        )
    artifact = build_human_markdown_archive(documents_snapshot)
    logger.info(
        "knowledge_export audience=human scope=library documents=%s elapsed_ms=%s",
        artifact.counts["documents"], round((time.perf_counter() - started) * 1000),
    )
    return FileResponse(
        artifact.path, media_type="application/zip", filename=artifact.filename,
        background=BackgroundTask(artifact.path.unlink, missing_ok=True),
    )


@app.get("/v1/exports/knowledge-package")
def export_knowledge_package(
    scope: Literal["library", "document"],
    document_id: str | None = None,
    user: dict = Depends(current_user),
):
    _validate_export_scope(scope, document_id)
    started = time.perf_counter()
    snapshot = store.export_knowledge_snapshot(user["id"], document_id=document_id)
    if snapshot is None:
        raise HTTPException(404, "Document not found")
    artifact = build_knowledge_archive(snapshot, scope=scope, document_id=document_id)
    logger.info(
        "knowledge_export audience=ai scope=%s documents=%s versions=%s elapsed_ms=%s",
        scope, artifact.counts["documents"], artifact.counts["document_versions"],
        round((time.perf_counter() - started) * 1000),
    )
    return FileResponse(
        artifact.path, media_type="application/zip", filename=artifact.filename,
        background=BackgroundTask(artifact.path.unlink, missing_ok=True),
    )


@app.get("/v1/documents/{document_id}/versions", response_model=list[DocumentVersion])
def list_document_versions(document_id: str, user: dict = Depends(current_user)):
    result = store.list_document_versions(user["id"], document_id)
    if result is None:
        raise HTTPException(404, "Document not found")
    return result


@app.get("/v1/documents/{document_id}", response_model=Document)
def get_document(document_id: str, user: dict = Depends(current_user)):
    result = store.get_document(user["id"], document_id)
    if not result:
        raise HTTPException(404, "Document not found")
    return result


@app.put("/v1/documents/{document_id}", response_model=Document)
def update_document(document_id: str, payload: DocumentUpdate, user: dict = Depends(current_user)):
    try:
        result = store.update_document(
            user["id"], document_id, title=payload.title, markdown=payload.markdown,
            base_version=payload.base_version, reason=payload.reason,
        )
    except DocumentVersionConflict as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "message": "文档已在其他位置更新，请载入最新版本后再保存",
            "code": "DOCUMENT_VERSION_CONFLICT",
            "current_version": exc.current_version,
        }) from exc
    if not result:
        raise HTTPException(404, "Document not found")
    if result["version"] != payload.base_version:
        submit_index_rebuild(
            user["id"], document_id, client_type="user-desktop", trigger="document_update",
        )
    return result


@app.post("/v1/documents/{document_id}/reindex", response_model=ReindexResponse)
def reindex_document(
    document_id: str, request: Request, user: dict = Depends(current_user),
):
    if not store.get_owned_document(user["id"], document_id):
        raise HTTPException(404, "Document not found")
    submit_index_rebuild(
        user["id"], document_id, request_id=request.state.request_id,
        client_type=request.state.client_type, trigger="manual_reindex",
    )
    if user.get("role") == "admin":
        _audit(request, user, "admin.document.reindex", "document", document_id, "success")
    return {"document_id": document_id, "chunks": 0, "status": "queued"}


@app.get("/v1/search", response_model=SearchResponse)
def search_documents(
    q: str = Query(..., min_length=1, max_length=4000),
    limit: int = Query(8, ge=1, le=50),
    include_public: bool = True,
    user: dict = Depends(current_user),
):
    query = q.strip()
    if not query:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "q must not be empty")
    retrieval = HybridRetriever(store, ai).retrieve(
        user["id"], query, final_count=limit, include_public=include_public,
    )
    return {
        "items": [
            {
                "document_id": item["document_id"], "title": item["document_title"],
                "excerpt": item["content"], "document_version": item["current_version"],
                "chunk_id": item["id"], "matching_mode": retrieval.retrieval_mode,
                "score": item.get("rerank_score", item.get("rrf_score", 0.0)),
                "visibility": item.get("visibility", "private"),
            } for item in retrieval.results
        ],
        "retrieval_mode": retrieval.retrieval_mode,
        "fallback_reason": retrieval.fallback_reason,
    }


@app.get("/v1/knowledge-events", response_model=list[KnowledgeEvent])
def list_knowledge_events(user: dict = Depends(current_user)):
    return store.list_events(user["id"])


@app.post("/v1/chat/sessions", response_model=ChatSession, status_code=201)
def create_chat_session(payload: ChatSessionCreate, user: dict = Depends(current_user)):
    return store.create_chat_session(user["id"], payload.title)


@app.get("/v1/chat/sessions", response_model=list[ChatSession])
def list_chat_sessions(user: dict = Depends(current_user)):
    return store.list_chat_sessions(user["id"])


@app.patch("/v1/chat/sessions/{session_id}", response_model=ChatSession)
def update_chat_session(
    session_id: str, payload: ChatSessionUpdate, user: dict = Depends(current_user),
):
    result = store.update_chat_session(user["id"], session_id, payload.title)
    if not result:
        raise HTTPException(404, "Chat session not found")
    return result


@app.delete("/v1/chat/sessions/{session_id}", status_code=204)
def delete_chat_session(session_id: str, response: Response, user: dict = Depends(current_user)):
    result = store.delete_chat_session(user["id"], session_id)
    if result == "not_found":
        raise HTTPException(404, "Chat session not found")
    if result == "busy":
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "message": "当前对话仍在生成回复", "code": "CHAT_SESSION_BUSY",
        })
    response.status_code = status.HTTP_204_NO_CONTENT
    return None


@app.get("/v1/chat/sessions/{session_id}/messages", response_model=list[ChatMessage])
def list_chat_messages(session_id: str, user: dict = Depends(current_user)):
    result = store.list_chat_messages(user["id"], session_id)
    if result is None:
        raise HTTPException(404, "Chat session not found")
    return result


def _chat_stream(
    user_id: str, user_message: dict, assistant_message: dict,
    request_id: str, client_type: str,
):
    completed = False
    outcome = "interrupted"
    started = time.perf_counter()
    first_delta_logged = False
    tokens = bind_request_context(request_id, client_type)
    user_token = bind_user_context(user_id)
    metrics.adjust_gauge("nerva_sse_active", 1)
    try:
        logger.info(
            "chat_generation_started user_id=%s session_id=%s assistant_message_id=%s model=%s",
            user_id, assistant_message["session_id"], assistant_message["id"], ai.model,
        )
        yield sse_event("start", {
            "session_id": assistant_message["session_id"],
            "user_message_id": user_message["id"],
            "assistant_message_id": assistant_message["id"],
        })
        messages = store.list_chat_messages(user_id, assistant_message["session_id"])
        if messages is None:
            raise RuntimeError("Chat session disappeared")
        query = user_message["content"]
        recent = [
            item["content"] for item in messages
            if item["role"] == "user" and item["id"] != user_message["id"]
        ][-4:]
        sources = retrieve_chat_sources(
            query, limit=5, store=store, user_id=user_id, provider=ai, recent_messages=recent,
            include_public=bool(user_message.get("include_public", True)),
        )
        history = build_chat_history(messages)
        active_memories = load_active_memories(store, user_id)
        chat_memories = [item for item in active_memories if item["kind"] in {"domain", "style"}]
        memory_block = chat_memory_block(chat_memories)
        logger.info(
            "chat_context_prepared user_id=%s session_id=%s history_messages=%s sources=%s memories=%s",
            user_id, assistant_message["session_id"], len(history), len(sources), len(chat_memories),
        )
        parser = ChatStreamParser(bool(sources))
        for chunk in ai.stream_chat(history, sources, memory_block=memory_block):
            for delta in parser.feed(chunk):
                if delta and not first_delta_logged:
                    first_delta_logged = True
                    logger.info(
                        "chat_first_delta user_id=%s session_id=%s assistant_message_id=%s elapsed_ms=%s",
                        user_id, assistant_message["session_id"], assistant_message["id"],
                        int((time.perf_counter() - started) * 1000),
                    )
                yield sse_event("delta", {"text": delta})
        for delta in parser.finish():
            if delta and not first_delta_logged:
                first_delta_logged = True
                logger.info(
                    "chat_first_delta user_id=%s session_id=%s assistant_message_id=%s elapsed_ms=%s",
                    user_id, assistant_message["session_id"], assistant_message["id"],
                    int((time.perf_counter() - started) * 1000),
                )
            yield sse_event("delta", {"text": delta})
        answer = parser.answer
        if not answer:
            raise AIProviderError("AI_INVALID_RESPONSE", "模型没有返回可用内容", retryable=True)
        citations = validated_citations(answer, sources)
        grounding = parser.grounding or ("knowledge" if citations else "general")
        if grounding in {"knowledge", "knowledge_plus_general"} and not citations:
            grounding = "general"
        saved = store.complete_chat_message(
            user_id, assistant_message["id"], content=answer,
            grounding=grounding, citations=citations,
        )
        if not saved:
            raise RuntimeError("Chat message is no longer generating")
        completed = True
        outcome = "completed"
        try:
            store.increment_memory_usage(user_id, [item["id"] for item in chat_memories])
        except Exception:
            logger.warning(
                "chat_memory_usage_update_failed user_id=%s message_id=%s",
                user_id, assistant_message["id"],
            )
        candidates = []
        if should_infer_memory(user_message["content"]):
            candidates = _try_infer_and_store_memories(
                ai, store, user_id, user_message["content"], "knowledge_chat",
            )
        if candidates:
            yield sse_event("memory_candidates", {"memories": candidates})
        logger.info(
            "chat_generation_completed user_id=%s session_id=%s assistant_message_id=%s "
            "grounding=%s citations=%s candidates=%s answer_chars=%s elapsed_ms=%s",
            user_id, assistant_message["session_id"], assistant_message["id"], grounding,
            len(citations), len(candidates), len(answer),
            int((time.perf_counter() - started) * 1000),
        )
        yield sse_event("done", {"message": saved})
    except GeneratorExit:
        if not completed:
            store.fail_chat_message(
                user_id, assistant_message["id"], "CHAT_CANCELLED", cancelled=True,
            )
            completed = True
            outcome = "cancelled"
            logger.info(
                "chat_generation_cancelled user_id=%s session_id=%s assistant_message_id=%s elapsed_ms=%s",
                user_id, assistant_message["session_id"], assistant_message["id"],
                int((time.perf_counter() - started) * 1000),
            )
        raise
    except AIProviderError as exc:
        store.fail_chat_message(user_id, assistant_message["id"], exc.code)
        metrics.increment("nerva_model_calls_total", operation="ai", status="failed")
        completed = True
        outcome = "failed"
        logger.warning(
            "chat_generation_failed user_id=%s session_id=%s assistant_message_id=%s "
            "error_code=%s retryable=%s upstream_status=%s elapsed_ms=%s",
            user_id, assistant_message["session_id"], assistant_message["id"], exc.code,
            exc.retryable, exc.upstream_status, int((time.perf_counter() - started) * 1000),
        )
        yield sse_event("error", {
            "code": exc.code,
            "message": "对话生成暂时失败，请稍后重试" if exc.retryable else "对话生成失败",
            "retryable": exc.retryable, "request_id": request_id,
        })
    except Exception as exc:
        logger.exception("chat generation failed message_id=%s", assistant_message["id"])
        store.fail_chat_message(user_id, assistant_message["id"], "CHAT_INTERNAL_ERROR")
        completed = True
        outcome = "failed"
        yield sse_event("error", {
            "code": "CHAT_INTERNAL_ERROR", "message": "对话生成失败，请稍后重试",
            "retryable": True, "request_id": request_id,
        })
    finally:
        if not completed:
            store.fail_chat_message(
                user_id, assistant_message["id"], "CHAT_CANCELLED", cancelled=True,
            )
        metrics.adjust_gauge("nerva_sse_active", -1)
        metrics.increment("nerva_chat_stream_total", outcome=outcome)
        try:
            from .logging_config import user_id_var
            user_id_var.reset(user_token)
        except (ValueError, RuntimeError):
            pass
        clear_request_context(tokens)


def _chat_streaming_response(
    user_id: str, user_message: dict, assistant_message: dict,
    request_id: str, client_type: str,
):
    return StreamingResponse(
        _chat_stream(user_id, user_message, assistant_message, request_id, client_type),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/v1/chat/sessions/{session_id}/messages")
def create_chat_message(
    session_id: str, payload: ChatMessageCreate, request: Request,
    user: dict = Depends(current_user),
):
    try:
        turn = store.create_chat_turn(
            user["id"], session_id, payload.content, ai.model,
            include_public=payload.include_public,
        )
    except ChatSessionBusy:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "message": "当前对话仍在生成回复", "code": "CHAT_ALREADY_GENERATING",
        })
    if not turn:
        raise HTTPException(404, "Chat session not found")
    return _chat_streaming_response(
        user["id"], *turn, request.state.request_id, request.state.client_type,
    )


@app.post("/v1/chat/messages/{message_id}/retry")
def retry_chat_message(
    message_id: str, request: Request, user: dict = Depends(current_user),
):
    try:
        turn = store.retry_chat_message(user["id"], message_id)
    except ChatSessionBusy:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "message": "当前对话仍在生成回复", "code": "CHAT_ALREADY_GENERATING",
        })
    if not turn:
        raise HTTPException(404, "Retryable chat message not found")
    return _chat_streaming_response(
        user["id"], *turn, request.state.request_id, request.state.client_type,
    )


@app.get("/v1/memories", response_model=list[Memory])
def list_memories(
    status: Literal["active", "candidate", "suppressed"] | None = None,
    user: dict = Depends(current_user),
):
    return store.list_memories(user["id"], status=status)


@app.post("/v1/memories", response_model=Memory, status_code=201)
def create_memory(payload: MemoryCreate, user: dict = Depends(current_user)):
    key = (payload.kind, normalize_memory_content(payload.content))
    if any(
        (item["kind"], normalize_memory_content(item["content"])) == key
        for item in store.list_memories(user["id"])
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "message": "相同偏好已经存在", "code": "MEMORY_DUPLICATE",
        })
    return store.create_memory(
        user["id"],
        kind=payload.kind,
        content=payload.content,
        scope="global",
        scope_ref=None,
        status="active",
        confidence=1.0,
        origin="user_explicit",
    )


@app.get("/v1/memories/{memory_id}", response_model=Memory)
def get_memory(memory_id: str, user: dict = Depends(current_user)):
    result = store.get_memory(user["id"], memory_id)
    if not result:
        raise HTTPException(404, "Memory not found")
    return result


@app.patch("/v1/memories/{memory_id}", response_model=Memory)
def update_memory(memory_id: str, payload: MemoryUpdate, user: dict = Depends(current_user)):
    current = store.get_memory(user["id"], memory_id)
    if not current:
        raise HTTPException(404, "Memory not found")
    if payload.status == "candidate" and current["status"] != "candidate":
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "message": "记忆状态不能回退为待确认", "code": "MEMORY_STATUS_TRANSITION_INVALID",
        })
    if payload.content is not None:
        key = (current["kind"], normalize_memory_content(payload.content))
        if any(
            item["id"] != memory_id
            and (item["kind"], normalize_memory_content(item["content"])) == key
            for item in store.list_memories(user["id"])
        ):
            raise HTTPException(status.HTTP_409_CONFLICT, detail={
                "message": "相同偏好已经存在", "code": "MEMORY_DUPLICATE",
            })
    result = store.update_memory(
        user["id"], memory_id,
        content=payload.content,
        status=payload.status,
    )
    if not result:
        raise HTTPException(404, "Memory not found")
    return result


@app.delete("/v1/memories/{memory_id}", status_code=204)
def delete_memory(memory_id: str, response: Response, user: dict = Depends(current_user)):
    if not store.delete_memory(user["id"], memory_id):
        raise HTTPException(404, "Memory not found")
    response.status_code = status.HTTP_204_NO_CONTENT
    return None
