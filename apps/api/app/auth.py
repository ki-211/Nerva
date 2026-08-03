import hashlib
import hmac
import secrets
from datetime import timedelta

from .settings import settings
from .store import Store, now_utc


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verification_code_hash(email: str, code: str) -> str:
    message = f"{normalize_email(email)}:{code}".encode("utf-8")
    return hmac.new(settings.verification_code_secret.encode("utf-8"), message, hashlib.sha256).hexdigest()


def create_session(store: Store, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    store.create_session(
        user_id=user_id,
        token_hash=token_hash(token),
        expires_at=now_utc() + timedelta(days=settings.session_days),
    )
    return token


def authenticate_session(store: Store, token: str | None) -> dict | None:
    if not token:
        return None
    return store.get_session_user(token_hash(token), now_utc())


def revoke_session(store: Store, token: str | None) -> None:
    if token:
        store.revoke_session(token_hash(token), now_utc())
