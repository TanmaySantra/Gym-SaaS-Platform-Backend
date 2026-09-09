"""
Password hashing (Argon2id) and JWT access/refresh token handling.

JWT payloads intentionally carry only: sub, gym_id, role, session_id, type, exp.
Never put passwords, member data, or financial data into a token (section 7).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import settings

# Argon2id via passlib, per section 7.
pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


class TokenType(str, Enum):
    ACCESS = "access"
    REFRESH = "refresh"


class InvalidTokenError(Exception):
    """Raised when a JWT is malformed, expired, or has the wrong type."""


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def _create_token(
    *,
    subject: str,
    gym_id: str | None,
    role: str,
    session_id: str,
    token_type: TokenType,
    expires_delta: timedelta,
    secret: str,
) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": subject,
        "gym_id": gym_id,
        "role": role,
        "session_id": session_id,
        "type": token_type.value,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, secret, algorithm=settings.JWT_ALGORITHM)


def create_access_token(*, subject: str, gym_id: str | None, role: str, session_id: str) -> str:
    return _create_token(
        subject=subject,
        gym_id=gym_id,
        role=role,
        session_id=session_id,
        token_type=TokenType.ACCESS,
        expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES),
        secret=settings.JWT_SECRET,
    )


def create_refresh_token(*, subject: str, gym_id: str | None, role: str, session_id: str) -> str:
    return _create_token(
        subject=subject,
        gym_id=gym_id,
        role=role,
        session_id=session_id,
        token_type=TokenType.REFRESH,
        expires_delta=timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS),
        secret=settings.JWT_REFRESH_SECRET,
    )


def decode_token(token: str, *, expected_type: TokenType) -> dict[str, Any]:
    """Decode + validate a JWT, raising InvalidTokenError on any problem."""
    secret = settings.JWT_SECRET if expected_type == TokenType.ACCESS else settings.JWT_REFRESH_SECRET
    try:
        payload = jwt.decode(token, secret, algorithms=[settings.JWT_ALGORITHM])
    except JWTError as exc:
        raise InvalidTokenError(str(exc)) from exc

    if payload.get("type") != expected_type.value:
        raise InvalidTokenError(f"Expected token type '{expected_type.value}', got '{payload.get('type')}'")

    return payload


def new_session_id() -> str:
    return str(uuid.uuid4())
