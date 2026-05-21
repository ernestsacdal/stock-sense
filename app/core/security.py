from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import bcrypt
from jose import JWTError, jwt

from app.core.config import get_settings

settings = get_settings()

# bcrypt rejects inputs longer than 72 bytes; we cap proactively so a long
# pasted password fails closed with a normal "wrong password" rather than
# raising deep inside the hashing library.
_BCRYPT_MAX = 72

TokenType = Literal["access", "refresh"]


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(_truncate(plain), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    return bcrypt.checkpw(_truncate(plain), hashed.encode("utf-8"))


def _truncate(plain: str) -> bytes:
    return plain.encode("utf-8")[:_BCRYPT_MAX]


def create_access_token(subject: str | int) -> str:
    return _encode(
        {"sub": str(subject), "type": "access"},
        timedelta(minutes=settings.jwt_access_ttl_min),
    )


def create_refresh_token(subject: str | int) -> str:
    return _encode(
        {"sub": str(subject), "type": "refresh"},
        timedelta(days=settings.jwt_refresh_ttl_days),
    )


class TokenError(Exception):
    pass


def decode_token(token: str, expected_type: TokenType) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except JWTError as exc:
        raise TokenError("invalid token") from exc

    if payload.get("type") != expected_type:
        raise TokenError(f"expected {expected_type} token, got {payload.get('type')!r}")

    return payload


def _encode(claims: dict[str, Any], ttl: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {**claims, "iat": int(now.timestamp()), "exp": int((now + ttl).timestamp())}
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
