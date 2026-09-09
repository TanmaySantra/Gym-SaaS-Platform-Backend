"""
User = the authentication identity. Every user has a role.
SUPER_ADMIN.gym_id is NULL (platform-level). OWNER/MEMBER.gym_id is required
and is the single source of truth the backend uses for tenant scoping — never
a value supplied by the client (section 5).
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.enums import UserRole
from app.core.database import Base

if TYPE_CHECKING:
    from app.gyms.models import Gym
    from app.members.models import Member


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        Index("ix_users_gym_id_role", "gym_id", "role"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # NULL for SUPER_ADMIN; required for OWNER/MEMBER. Enforced in service layer
    # (a DB-level CHECK constraint mirroring this is added in the migration).
    gym_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gyms.id", ondelete="CASCADE"), nullable=True, index=True
    )

    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole, name="user_role"), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    gym: Mapped[Optional["Gym"]] = relationship(back_populates="users")
    member_profile: Mapped[Optional["Member"]] = relationship(
        back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
