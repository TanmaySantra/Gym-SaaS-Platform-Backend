"""
MembershipPlan = a gym-defined plan (e.g. "Monthly", "Annual").
Membership = a specific member's subscription to a plan, carrying the
human-shareable membership_id (section 8) and the lifecycle status machine
(section 9): ACTIVE -> PAYMENT_DUE -> RESTRICTED, EXPIRED, CANCELLED.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.enums import MembershipStatus
from app.core.database import Base

if TYPE_CHECKING:
    from app.gyms.models import Gym
    from app.members.models import Member
    from app.payments.models import Payment


class MembershipPlan(Base):
    __tablename__ = "membership_plans"
    __table_args__ = (Index("ix_membership_plans_gym_id", "gym_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gym_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gyms.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False)
    price: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    gym: Mapped["Gym"] = relationship()
    memberships: Mapped[list["Membership"]] = relationship(back_populates="plan")


class Membership(Base):
    __tablename__ = "memberships"
    __table_args__ = (
        Index("ix_memberships_gym_id", "gym_id"),
        Index("ix_memberships_member_id", "member_id"),
        Index("ix_memberships_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    gym_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gyms.id", ondelete="CASCADE"), nullable=False
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("membership_plans.id", ondelete="RESTRICT"), nullable=False
    )

    # Human-shareable identifier, e.g. "GYM001-8F42K" (section 8). Never used as a password.
    membership_id_code: Mapped[str] = mapped_column(String(32), unique=True, nullable=False, index=True)

    # True once a MEMBER-role user has linked this membership via the code.
    is_linked: Mapped[bool] = mapped_column(default=False, nullable=False)

    status: Mapped[MembershipStatus] = mapped_column(
        Enum(MembershipStatus, name="membership_status"), nullable=False, default=MembershipStatus.ACTIVE
    )

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Set the moment a payment is missed; cleared when payment is made.
    # Celery Beat reads this to compute elapsed overdue days (section 12/35).
    payment_due_since: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    restricted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    gym: Mapped["Gym"] = relationship()
    member: Mapped["Member"] = relationship(back_populates="memberships")
    plan: Mapped["MembershipPlan"] = relationship(back_populates="memberships")
    payments: Mapped[list["Payment"]] = relationship(back_populates="membership")
