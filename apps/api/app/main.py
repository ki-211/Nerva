import secrets
import smtplib
import logging
from datetime import timedelta

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware

from .ai import get_ai_adapter
from .auth import (
    authenticate_session, create_session, normalize_email, revoke_session,
    verification_code_hash,
)
from .mailer import send_registration_code
from .logging_config import configure_logging
from .schemas import (
    ApplyChangeSet, ChangeSet, Document, IngestionCreate, KnowledgeEvent,
    CodeLoginRequest, SendVerificationCodeRequest, User,
)
from .settings import settings
from .store import Store, now_utc


configure_logging()
logger = logging.getLogger("nerva.api")
app = FastAPI(title="Nerva API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(settings.cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

store = Store(settings.sqlalchemy_url(), create_schema=False)
ai = get_ai_adapter()


@app.middleware("http")
async def reject_untrusted_origins(request: Request, call_next):
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        origin = request.headers.get("origin")
        if origin and origin not in settings.cors_origins:
            return Response(status_code=status.HTTP_403_FORBIDDEN)
    try:
        return await call_next(request)
    except Exception:
        logger.exception("unhandled request error method=%s path=%s", request.method, request.url.path)
        raise


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
    return user


@app.get("/health")
def health():
    return {"status": "ok", "version": app.version, "ai_provider": settings.ai_provider}


@app.post("/v1/auth/code-login", response_model=User)
def code_login(payload: CodeLoginRequest, response: Response):
    email = normalize_email(str(payload.email))
    if not store.consume_verification_code(
        email, verification_code_hash(email, payload.verification_code), now_utc()
    ):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "验证码错误或已过期")
    user = store.get_user_by_email(email)
    if user and user["status"] != "active":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "账号已停用")
    if not user:
        user = store.create_user(email, email.split("@", 1)[0][:80])
    set_session_cookie(response, create_session(store, user["id"]))
    return user


@app.post("/v1/auth/verification-codes", status_code=204)
def send_verification_code(payload: SendVerificationCodeRequest, response: Response):
    email = normalize_email(str(payload.email))
    now = now_utc()
    if store.verification_code_is_cooling_down(email, now):
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
    response.delete_cookie(settings.session_cookie_name, path="/", samesite="lax")
    response.status_code = status.HTTP_204_NO_CONTENT
    return None


@app.get("/v1/auth/me", response_model=User)
def me(user: dict = Depends(current_user)):
    return user


@app.post("/v1/ingestions", response_model=ChangeSet, status_code=201)
def create_ingestion(payload: IngestionCreate, user: dict = Depends(current_user)):
    proposal = ai.propose(payload.content, payload.title, store.list_documents(user["id"]))
    return store.create_change_set(user["id"], payload.kind, payload.content, payload.title, proposal)


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
    return result


@app.get("/v1/documents", response_model=list[Document])
def list_documents(user: dict = Depends(current_user)):
    return store.list_documents(user["id"])


@app.get("/v1/knowledge-events", response_model=list[KnowledgeEvent])
def list_knowledge_events(user: dict = Depends(current_user)):
    return store.list_events(user["id"])
