"""AI insight storage (section 19-20). Only ever written after Pydantic-validated
model output — never raw/untrusted model text."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.enums import RiskLevel
from app.core.database import Base

if TYPE_CHECKING:
    from app.members.models import Member


class AIInsight(Base):
    __tablename__ = "ai_insights"
    __table_args__ = (
        Index("ix_ai_insights_gym_id", "gym_id"),
        Index("ix_ai_insights_member_id", "member_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gym_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gyms.id", ondelete="CASCADE"), nullable=False
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )

    risk_level: Mapped[RiskLevel] = mapped_column(Enum(RiskLevel, name="ai_risk_level"), nullable=False)
    insight: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    recommended_action: Mapped[str] = mapped_column(Text, nullable=False)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    member: Mapped["Member"] = relationship()
