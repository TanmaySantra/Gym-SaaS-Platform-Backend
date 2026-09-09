"""
Member service layer.

Every read/write here takes gym_id as a required parameter and filters by it
at the query level (never "fetch then check") — this is what makes cross-
tenant IDOR structurally impossible rather than just checked (section 5/34).
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.audit import log_audit_event
from app.common.enums import UserRole
from app.common.pagination import PageParams, paginate
from app.common.responses import PaginatedData
from app.core.exceptions import ConflictError, NotFoundError
from app.core.security import hash_password
from app.members.models import Member
from app.memberships.models import Membership
from app.users.models import User


def create_member(
    db: Session, *, actor_id: uuid.UUID, gym_id: uuid.UUID, full_name: str, phone: str | None, date_of_birth
) -> Member:
    member = Member(gym_id=gym_id, full_name=full_name, phone=phone, date_of_birth=date_of_birth)
    db.add(member)
    db.flush()

    log_audit_event(
        db, actor_user_id=actor_id, gym_id=gym_id, action="MEMBER_CREATED",
        entity_type="member", entity_id=str(member.id), metadata={"full_name": full_name},
    )
    db.commit()
    db.refresh(member)
    return member


def list_members(db: Session, *, gym_id: uuid.UUID, params: PageParams) -> PaginatedData:
    stmt = select(Member).where(Member.gym_id == gym_id).order_by(Member.created_at.desc())
    return paginate(db, stmt, params)


def get_member(db: Session, *, gym_id: uuid.UUID, member_id: uuid.UUID) -> Member:
    """
    Scoped by gym_id in the WHERE clause itself. A member_id belonging to
    another gym simply doesn't match this query — it returns NotFoundError,
    not a 403, so cross-tenant probing can't distinguish 'wrong tenant' from
    'doesn't exist' (section 34).
    """
    member = db.scalar(select(Member).where(Member.id == member_id, Member.gym_id == gym_id))
    if member is None:
        raise NotFoundError("Member not found.", code="MEMBER_NOT_FOUND")
    return member


def get_member_by_user_id(db: Session, *, gym_id: uuid.UUID, user_id: uuid.UUID) -> Member:
    """Resolves the Member profile for the currently authenticated MEMBER-role
    user — used by every member-facing self-service endpoint (workouts,
    progress, attendance, membership views)."""
    member = db.scalar(select(Member).where(Member.user_id == user_id, Member.gym_id == gym_id))
    if member is None:
        raise NotFoundError("Member profile not found for this account.", code="MEMBER_PROFILE_NOT_FOUND")
    return member


def link_membership(db: Session, *, membership_id_code: str, email: str, password: str) -> tuple[Member, User]:
    """
    Public flow (section 8): a prospective member enters the code the owner
    gave them, plus their own chosen email/password, to create their login
    and link it to the Member profile the owner already created.
    """
    membership = db.scalar(select(Membership).where(Membership.membership_id_code == membership_id_code))
    if membership is None:
        raise NotFoundError("Invalid membership ID.", code="INVALID_MEMBERSHIP_ID")

    member = db.get(Member, membership.member_id)
    if member is None or member.user_id is not None:
        raise ConflictError("This membership ID has already been linked to an account.", code="ALREADY_LINKED")

    existing_user = db.scalar(select(User).where(User.email == email.lower()))
    if existing_user is not None:
        raise ConflictError(f"A user with email '{email}' already exists.", code="EMAIL_TAKEN")

    user = User(
        email=email.lower(),
        full_name=member.full_name,
        hashed_password=hash_password(password),
        role=UserRole.MEMBER,
        gym_id=member.gym_id,
        is_active=True,
    )
    db.add(user)
    db.flush()

    member.user_id = user.id
    membership.is_linked = True

    log_audit_event(
        db, actor_user_id=user.id, gym_id=member.gym_id, action="MEMBER_LINKED",
        entity_type="member", entity_id=str(member.id), metadata={"email": user.email},
    )
    db.commit()
    db.refresh(member)
    db.refresh(user)
    return member, user
