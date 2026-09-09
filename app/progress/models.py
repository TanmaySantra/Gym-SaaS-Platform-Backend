"""Progress records (section 16). Creation is blocked while RESTRICTED; historical
rows are never deleted when a membership changes state."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.members.models import Member


class ProgressRecord(Base):
    __tablename__ = "progress_records"
    __table_args__ = (
        Index("ix_progress_records_gym_id", "gym_id"),
        Index("ix_progress_records_member_id_recorded_at", "member_id", "recorded_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gym_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gyms.id", ondelete="CASCADE"), nullable=False
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )

    weight_kg: Mapped[Optional[float]] = mapped_column(Numeric(6, 2), nullable=True)
    height_cm: Mapped[Optional[float]] = mapped_column(Numeric(6, 2), nullable=True)
    chest_cm: Mapped[Optional[float]] = mapped_column(Numeric(6, 2), nullable=True)
    waist_cm: Mapped[Optional[float]] = mapped_column(Numeric(6, 2), nullable=True)
    arms_cm: Mapped[Optional[float]] = mapped_column(Numeric(6, 2), nullable=True)
    thighs_cm: Mapped[Optional[float]] = mapped_column(Numeric(6, 2), nullable=True)

    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    member: Mapped["Member"] = relationship()
