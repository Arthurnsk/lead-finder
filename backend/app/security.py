"""Password hashing, JWT cookies, CSRF, encryption of secrets at rest, login rate limiting."""

from __future__ import annotations

import json
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

_ph = PasswordHasher()

ACCESS_COOKIE = "lf_access"
REFRESH_COOKIE = "lf_refresh"
CSRF_COOKIE = "lf_csrf"
CSRF_HEADER = "X-CSRF-Token"


# ---------------------------------------------------------------- passwords


def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return _ph.verify(password_hash, password)
    except (VerifyMismatchError, Exception):
        return False


# ---------------------------------------------------------------- JWT


def _encode(sub: uuid.UUID, kind: str, ttl: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": str(sub), "typ": kind, "iat": now, "exp": now + ttl, "jti": secrets.token_hex(8)}
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def create_access_token(user_id: uuid.UUID) -> str:
    return _encode(user_id, "access", timedelta(minutes=settings.access_token_minutes))


def create_refresh_token(user_id: uuid.UUID) -> str:
    return _encode(user_id, "refresh", timedelta(days=settings.refresh_token_days))


def decode_token(token: str, kind: str) -> uuid.UUID | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != kind:
        return None
    try:
        return uuid.UUID(payload["sub"])
    except (KeyError, ValueError):
        return None


def new_csrf_token() -> str:
    return secrets.token_urlsafe(24)


# ---------------------------------------------------------------- secrets at rest


def _fernet() -> Fernet:
    if not settings.fernet_key:
        raise RuntimeError("FERNET_KEY не задан: сгенерируйте `python manage.py gen-key` и добавьте в .env")
    return Fernet(settings.fernet_key.encode())


def encrypt_json(data: dict) -> str:
    return _fernet().encrypt(json.dumps(data, ensure_ascii=False).encode()).decode()


def decrypt_json(token: str) -> dict:
    if not token:
        return {}
    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken as exc:
        raise RuntimeError("Не удалось расшифровать секрет: FERNET_KEY изменился?") from exc


# ---------------------------------------------------------------- rate limit (per-process sliding window)


class RateLimiter:
    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[str, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] > 60:
                q.popleft()
            if len(q) >= self.per_minute:
                return False
            q.append(now)
            return True


login_limiter = RateLimiter(settings.login_rate_per_minute)
