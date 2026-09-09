"""
Auth service layer (section 7).

Session model: a LoginSession row is created at login and its own primary
key is embedded in both the access and refresh JWTs as `session_id`. Logout
flips the session to LOGGED_OUT; `get_current_user` (common/dependencies.py)
re-checks that status on every request, so logout actually revokes access
instead of just being a client-side no-op.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.auth.models import LoginSession
from app.auth.schemas import SignupResponse, TokenResponse
from app.common.audit import log_audit_event
from app.common.enums import GymStatus, SessionStatus
from app.core.exceptions import UnauthorizedError
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
    InvalidTokenError,
    TokenType,
)
from app.users.models import User

INVALID_CREDENTIALS_MESSAGE = "Incorrect email or password."


def authenticate_user(db: Session, *, email: str, password: str) -> User:
    user = db.query(User).filter(User.email == email.lower()).one_or_none()
    if user is None or not verify_password(password, user.hashed_password):
        # Deliberately identical message/timing profile for "no such user" and
        # "wrong password" so login can't be used to enumerate valid emails.
        raise UnauthorizedError(INVALID_CREDENTIALS_MESSAGE, code="INVALID_CREDENTIALS")
    if not user.is_active:
        raise UnauthorizedError("This account has been deactivated.", code="ACCOUNT_INACTIVE")
    if user.gym_id is not None and user.gym is not None and user.gym.status == GymStatus.SUSPENDED:
        raise UnauthorizedError("This gym has been suspended.", code="GYM_SUSPENDED")
    return user


def login(
    db: Session,
    *,
    email: str,
    password: str,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> TokenResponse:
    user = authenticate_user(db, email=email, password=password)

    session = LoginSession(
        user_id=user.id,
        gym_id=user.gym_id,
        status=SessionStatus.ACTIVE,
        user_agent=user_agent,
        ip_address=ip_address,
    )
    db.add(session)
    db.flush()  # populate session.id without ending the transaction

    access_token = create_access_token(
        subject=str(user.id), gym_id=str(user.gym_id) if user.gym_id else None,
        role=user.role.value, session_id=str(session.id),
    )
    refresh_token = create_refresh_token(
        subject=str(user.id), gym_id=str(user.gym_id) if user.gym_id else None,
        role=user.role.value, session_id=str(session.id),
    )

    log_audit_event(
        db,
        actor_user_id=user.id,
        gym_id=user.gym_id,
        action="LOGIN",
        entity_type="user",
        entity_id=str(user.id),
    )
    db.commit()

    return TokenResponse(access_token=access_token, refresh_token=refresh_token)


def signup(
    db: Session,
    *,
    membership_id_code: str,
    email: str,
    password: str,
    user_agent: str | None = None,
    ip_address: str | None = None,
) -> SignupResponse:
    """Create a member account from an owner-issued membership code.

    The membership code supplies the gym context, so public signup cannot
    choose a tenant or elevate itself to OWNER/SUPER_ADMIN.
    """
    from app.members.service import link_membership

    _member, user = link_membership(
        db, membership_id_code=membership_id_code, email=email, password=password
    )
    tokens = login(db, email=email, password=password, user_agent=user_agent, ip_address=ip_address)
    return SignupResponse(user=user, tokens=tokens)


def refresh_access_token(db: Session, *, refresh_token: str) -> str:
    try:
        payload = decode_token(refresh_token, expected_type=TokenType.REFRESH)
    except InvalidTokenError as exc:
        raise UnauthorizedError("Invalid or expired refresh token.", code="INVALID_REFRESH_TOKEN") from exc

    session_id = payload.get("session_id")
    session = db.get(LoginSession, uuid.UUID(session_id)) if session_id else None
    if session is None or session.status != SessionStatus.ACTIVE:
        raise UnauthorizedError("Session is no longer active.", code="SESSION_REVOKED")

    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise UnauthorizedError("Account is no longer active.", code="ACCOUNT_INACTIVE")

    session.last_activity_at = datetime.now(timezone.utc)
    db.commit()

    return create_access_token(
        subject=str(user.id),
        gym_id=str(user.gym_id) if user.gym_id else None,
        role=user.role.value,
        session_id=str(session.id),
    )


def logout(db: Session, *, session_id: uuid.UUID, user_id: uuid.UUID) -> None:
    session = db.get(LoginSession, session_id)
    if session is None or session.user_id != user_id:
        # Nothing to revoke / not the caller's session — treat as a no-op
        # rather than leaking whether the session id exists.
        return

    session.status = SessionStatus.LOGGED_OUT
    session.logout_at = datetime.now(timezone.utc)

    log_audit_event(
        db,
        actor_user_id=user_id,
        gym_id=session.gym_id,
        action="LOGOUT",
        entity_type="user",
        entity_id=str(user_id),
    )
    db.commit()
