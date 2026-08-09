import hashlib
import hmac
import secrets
import base64
import binascii
from datetime import timedelta

from .settings import settings
from .store import Store, now_utc


PASSWORD_SCHEME = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 310_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS,
    )
    return "$".join((PASSWORD_SCHEME, str(PASSWORD_ITERATIONS),
                     base64.urlsafe_b64encode(salt).decode("ascii"),
                     base64.urlsafe_b64encode(digest).decode("ascii")))


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        return False
    try:
        scheme, iterations, salt_text, digest_text = encoded.split("$", 3)
        if scheme != PASSWORD_SCHEME:
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode("ascii"))
        expected = base64.urlsafe_b64decode(digest_text.encode("ascii"))
        actual = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), salt, int(iterations),
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError, UnicodeError, binascii.Error):
        return False


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
