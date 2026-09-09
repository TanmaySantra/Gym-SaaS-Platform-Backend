"""
Platform-admin service layer (section 24).

Every mutating function here takes `actor_id` and writes an audit_logs row
in the SAME transaction as the change it's recording (section 22).
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin.schemas import PlatformStatsOut
from app.auth.models import LoginSession
from app.common.audit import log_audit_event
from app.common.enums import GymStatus, UserRole
from app.common.pagination import PageParams, paginate
from app.common.responses import PaginatedData
from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import hash_password
from app.gyms.models import Gym
from app.members.models import Member
from app.users.models import User


def create_gym(db: Session, *, actor_id: uuid.UUID, name: str, slug: str) -> Gym:
    existing = db.scalar(select(Gym).where(Gym.slug == slug))
    if existing is not None:
        raise ConflictError(f"A gym with slug '{slug}' already exists.", code="GYM_SLUG_TAKEN")

    gym = Gym(name=name, slug=slug, status=GymStatus.ACTIVE)
    db.add(gym)
    db.flush()

    log_audit_event(
        db, actor_user_id=actor_id, gym_id=gym.id, action="GYM_CREATED",
        entity_type="gym", entity_id=str(gym.id), metadata={"name": name, "slug": slug},
    )
    db.commit()
    db.refresh(gym)
    return gym


def list_gyms(db: Session, params: PageParams) -> PaginatedData:
    stmt = select(Gym).order_by(Gym.created_at.desc())
    return paginate(db, stmt, params)


def get_gym_detail(db: Session, *, gym_id: uuid.UUID) -> dict:
    gym = db.get(Gym, gym_id)
    if gym is None:
        raise NotFoundError("Gym not found.", code="GYM_NOT_FOUND")

    owner_count = db.scalar(
        select(func.count()).select_from(User).where(User.gym_id == gym_id, User.role == UserRole.OWNER)
    ) or 0
    member_count = db.scalar(select(func.count()).select_from(Member).where(Member.gym_id == gym_id)) or 0

    return {"gym": gym, "owner_count": owner_count, "member_count": member_count}


def suspend_gym(db: Session, *, actor_id: uuid.UUID, gym_id: uuid.UUID) -> Gym:
    gym = db.get(Gym, gym_id)
    if gym is None:
        raise NotFoundError("Gym not found.", code="GYM_NOT_FOUND")

    if gym.status != GymStatus.SUSPENDED:
        gym.status = GymStatus.SUSPENDED
        log_audit_event(
            db, actor_user_id=actor_id, gym_id=gym.id, action="GYM_SUSPENDED",
            entity_type="gym", entity_id=str(gym.id),
        )
        db.commit()
        db.refresh(gym)
    return gym


def activate_gym(db: Session, *, actor_id: uuid.UUID, gym_id: uuid.UUID) -> Gym:
    gym = db.get(Gym, gym_id)
    if gym is None:
        raise NotFoundError("Gym not found.", code="GYM_NOT_FOUND")

    if gym.status != GymStatus.ACTIVE:
        gym.status = GymStatus.ACTIVE
        log_audit_event(
            db, actor_user_id=actor_id, gym_id=gym.id, action="GYM_ACTIVATED",
            entity_type="gym", entity_id=str(gym.id),
        )
        db.commit()
        db.refresh(gym)
    return gym


def create_owner(db: Session, *, actor_id: uuid.UUID, gym_id: uuid.UUID, email: str, full_name: str, password: str) -> User:
    gym = db.get(Gym, gym_id)
    if gym is None:
        raise NotFoundError("Gym not found.", code="GYM_NOT_FOUND")

    existing = db.scalar(select(User).where(User.email == email.lower()))
    if existing is not None:
        raise ConflictError(f"A user with email '{email}' already exists.", code="EMAIL_TAKEN")

    owner = User(
        email=email.lower(),
        full_name=full_name,
        hashed_password=hash_password(password),
        role=UserRole.OWNER,
        gym_id=gym_id,
        is_active=True,
    )
    db.add(owner)
    db.flush()

    log_audit_event(
        db, actor_user_id=actor_id, gym_id=gym_id, action="OWNER_CREATED",
        entity_type="user", entity_id=str(owner.id), metadata={"email": owner.email},
    )
    db.commit()
    db.refresh(owner)
    return owner


def platform_stats(db: Session) -> PlatformStatsOut:
    total_gyms = db.scalar(select(func.count()).select_from(Gym)) or 0
    active_gyms = db.scalar(select(func.count()).select_from(Gym).where(Gym.status == GymStatus.ACTIVE)) or 0
    total_owners = db.scalar(select(func.count()).select_from(User).where(User.role == UserRole.OWNER)) or 0
    total_members = db.scalar(select(func.count()).select_from(Member)) or 0
    return PlatformStatsOut(
        total_gyms=total_gyms, active_gyms=active_gyms, total_owners=total_owners, total_members=total_members
    )


def list_audit_logs(db: Session, params: PageParams) -> PaginatedData:
    from app.common.models import AuditLog

    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    return paginate(db, stmt, params)


def list_login_sessions(db: Session, params: PageParams, *, user_id: uuid.UUID | None = None) -> PaginatedData:
    stmt = select(LoginSession).order_by(LoginSession.login_at.desc())
    if user_id is not None:
        stmt = stmt.where(LoginSession.user_id == user_id)
    return paginate(db, stmt, params)
