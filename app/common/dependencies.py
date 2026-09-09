"""
Shared FastAPI dependencies: authentication, role authorization, and tenant
resolution.

Section 5 is enforced here and ONLY here: `require_tenant_gym_id` derives the
tenant strictly from the authenticated user's own gym_id, which itself comes
from the JWT/session — never from a query/path/body parameter. Every router
that needs tenant scoping should depend on this rather than reading gym_id
off the request.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.auth.models import LoginSession
from app.common.enums import SessionStatus, UserRole
from app.core.database import get_db
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import InvalidTokenError, TokenType, decode_token
from app.users.models import User

_bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthContext:
    """Everything a route/service needs about 'who is calling right now'."""

    user: User
    session_id: uuid.UUID

    @property
    def role(self) -> UserRole:
        return self.user.role

    @property
    def gym_id(self) -> uuid.UUID | None:
        return self.user.gym_id


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: Session = Depends(get_db),
) -> AuthContext:
    if credentials is None or not credentials.credentials:
        raise UnauthorizedError("Missing or invalid authentication credentials.", code="MISSING_TOKEN")

    try:
        payload = decode_token(credentials.credentials, expected_type=TokenType.ACCESS)
    except InvalidTokenError as exc:
        raise UnauthorizedError("Invalid or expired access token.", code="INVALID_TOKEN") from exc

    session_id_raw = payload.get("session_id")
    try:
        session_id = uuid.UUID(session_id_raw)
        user_id = uuid.UUID(payload["sub"])
    except (TypeError, ValueError, KeyError) as exc:
        raise UnauthorizedError("Malformed token payload.", code="INVALID_TOKEN") from exc

    # Session must still be ACTIVE — this is what makes logout actually revoke
    # access instead of the client simply discarding an otherwise-valid JWT.
    session = db.get(LoginSession, session_id)
    if session is None or session.status != SessionStatus.ACTIVE:
        raise UnauthorizedError("Session is no longer active.", code="SESSION_REVOKED")

    user = db.get(User, user_id)
    if user is None or not user.is_active:
        raise UnauthorizedError("Account is no longer active.", code="ACCOUNT_INACTIVE")

    # Heartbeat / last-activity update (section 23) — best-effort, not
    # critical-path, so failures here should never break the request.
    session.last_activity_at = datetime.now(timezone.utc)
    db.commit()

    return AuthContext(user=user, session_id=session_id)


def require_roles(*allowed_roles: UserRole):
    """Dependency factory: 403s if the caller's role isn't in allowed_roles."""

    def _dependency(ctx: AuthContext = Depends(get_current_user)) -> AuthContext:
        if ctx.role not in allowed_roles:
            raise ForbiddenError(
                f"Role '{ctx.role.value}' is not permitted to perform this action.",
                code="ROLE_NOT_PERMITTED",
            )
        return ctx

    return _dependency


def require_tenant_gym_id(ctx: AuthContext = Depends(require_roles(UserRole.OWNER, UserRole.MEMBER))) -> uuid.UUID:
    """
    Returns the caller's OWN gym_id, derived solely from their authenticated
    session. Route handlers must use this value for every tenant-scoped query
    and must never accept an equivalent value from the client (section 5).
    """
    if ctx.gym_id is None:
        # Should be unreachable given DB-level invariants, but fail closed.
        raise ForbiddenError("No gym associated with this account.", code="NO_TENANT_CONTEXT")
    return ctx.gym_id


def get_current_member(ctx: AuthContext = Depends(require_roles(UserRole.MEMBER)), db: Session = Depends(get_db)):
    """
    Resolves the Member profile row for the calling MEMBER-role user. Used
    by every member-facing self-service endpoint (workouts, progress,
    attendance, membership views) so those routers never need to accept a
    member_id from the client — it's always derived from the session.
    """
    from app.members.service import get_member_by_user_id  # local import avoids a module cycle at import time

    return get_member_by_user_id(db, gym_id=ctx.gym_id, user_id=ctx.user.id)
