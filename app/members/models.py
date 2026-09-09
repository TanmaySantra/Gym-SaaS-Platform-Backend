"""
Member = gym-specific profile data, one-to-one with a User whose role is MEMBER.
gym_id is denormalized onto this table (in addition to being derivable via user)
so every tenant-scoped query can filter directly on Member.gym_id without a join,
per section 4 ("every tenant-owned entity must contain gym_id").
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.gyms.models import Gym
    from app.memberships.models import Membership
    from app.users.models import User


class Member(Base):
    __tablename__ = "members"
    __table_args__ = (
        Index("ix_members_gym_id", "gym_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    gym_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gyms.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), unique=True, nullable=True
    )

    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    date_of_birth: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    gym: Mapped["Gym"] = relationship()
    user: Mapped[Optional["User"]] = relationship(back_populates="member_profile")
    memberships: Mapped[list["Membership"]] = relationship(back_populates="member", cascade="all, delete-orphan")

    @property
    def is_linked(self) -> bool:
        """True once a MEMBER-role login has been linked via a membership ID."""
        return self.user_id is not None
