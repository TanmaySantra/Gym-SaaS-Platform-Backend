"""
Notification service layer (section 21).

`create_notification` is called from OTHER modules (memberships, AI) at the
moment something notification-worthy happens — it's the one integration
point, deliberately channel-agnostic (in-app only in V1) so email/WhatsApp
delivery could be added later without touching callers.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.enums import NotificationType, UserRole
from app.common.pagination import PageParams, paginate
from app.common.responses import PaginatedData
from app.core.exceptions import NotFoundError
from app.notifications.models import Notification


def create_notification(
    db: Session, *, gym_id: uuid.UUID, user_id: uuid.UUID, member_id: uuid.UUID | None,
    type: NotificationType, title: str, message: str,
) -> Notification:
    """Does NOT commit — caller includes this in whatever transaction is
    already in progress (e.g. the same commit as a membership state change)."""
    notification = Notification(
        gym_id=gym_id, user_id=user_id, member_id=member_id, type=type, title=title, message=message
    )
    db.add(notification)
    db.flush()
    return notification


def notify_member(
    db: Session, *, gym_id: uuid.UUID, member, type: NotificationType, title: str, message: str
) -> Notification | None:
    """Convenience wrapper: notifies a Member's linked user account, or does
    nothing if they haven't linked one yet (nothing to notify)."""
    if member is None or member.user_id is None:
        return None
    return create_notification(
        db, gym_id=gym_id, user_id=member.user_id, member_id=member.id, type=type, title=title, message=message
    )


def notify_gym_owners(
    db: Session, *, gym_id: uuid.UUID, member_id: uuid.UUID | None, type: NotificationType, title: str, message: str
) -> list[Notification]:
    """Notifies every OWNER-role user for this gym (there's normally one,
    but the schema doesn't prevent more)."""
    from app.users.models import User

    owner_ids = list(db.scalars(select(User.id).where(User.gym_id == gym_id, User.role == UserRole.OWNER)))
    return [
        create_notification(db, gym_id=gym_id, user_id=owner_id, member_id=member_id, type=type, title=title, message=message)
        for owner_id in owner_ids
    ]


def has_recent_notification(db: Session, *, member_id: uuid.UUID, type: NotificationType, since: date) -> bool:
    """Dedup guard so a repeated scheduled check doesn't spam the same
    member with the same notification every run."""
    exists = db.scalar(
        select(Notification.id).where(
            Notification.member_id == member_id, Notification.type == type, Notification.created_at >= since
        )
    )
    return exists is not None


def list_notifications_for_user(
    db: Session, *, gym_id: uuid.UUID, user_id: uuid.UUID, params: PageParams, unread_only: bool = False
) -> PaginatedData:
    stmt = select(Notification).where(Notification.gym_id == gym_id, Notification.user_id == user_id)
    if unread_only:
        stmt = stmt.where(Notification.read.is_(False))
    stmt = stmt.order_by(Notification.created_at.desc())
    return paginate(db, stmt, params)


def mark_as_read(db: Session, *, gym_id: uuid.UUID, user_id: uuid.UUID, notification_id: uuid.UUID) -> Notification:
    notification = db.scalar(
        select(Notification).where(
            Notification.id == notification_id, Notification.gym_id == gym_id, Notification.user_id == user_id
        )
    )
    if notification is None:
        raise NotFoundError("Notification not found.", code="NOTIFICATION_NOT_FOUND")
    notification.read = True
    db.commit()
    db.refresh(notification)
    return notification


def mark_all_as_read(db: Session, *, gym_id: uuid.UUID, user_id: uuid.UUID) -> int:
    stmt = select(Notification).where(
        Notification.gym_id == gym_id, Notification.user_id == user_id, Notification.read.is_(False)
    )
    unread = list(db.scalars(stmt))
    for n in unread:
        n.read = True
    db.commit()
    return len(unread)
