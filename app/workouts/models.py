"""
Workout structure (section 15):
    WorkoutPlan -> WorkoutPlanExercise -> Exercise
    WorkoutSession -> ExerciseLog (actual sets/reps/weight performed)

WorkoutSession/ExerciseLog creation is what gets blocked when a membership is
RESTRICTED (section 10) — enforced in the service layer, not here.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.enums import WorkoutSessionStatus
from app.core.database import Base

if TYPE_CHECKING:
    from app.gyms.models import Gym
    from app.members.models import Member


class Exercise(Base):
    """Gym-level exercise catalog entry (e.g. "Bench Press")."""

    __tablename__ = "exercises"
    __table_args__ = (Index("ix_exercises_gym_id", "gym_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gym_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gyms.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    muscle_group: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)

    gym: Mapped["Gym"] = relationship()


class WorkoutPlan(Base):
    __tablename__ = "workout_plans"
    __table_args__ = (Index("ix_workout_plans_gym_id", "gym_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gym_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gyms.id", ondelete="CASCADE"), nullable=False
    )
    member_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=True
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    gym: Mapped["Gym"] = relationship()
    plan_exercises: Mapped[list["WorkoutPlanExercise"]] = relationship(
        back_populates="workout_plan", cascade="all, delete-orphan", order_by="WorkoutPlanExercise.order_index"
    )


class WorkoutPlanExercise(Base):
    __tablename__ = "workout_plan_exercises"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workout_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workout_plans.id", ondelete="CASCADE"), nullable=False
    )
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exercises.id", ondelete="RESTRICT"), nullable=False
    )
    order_index: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    target_sets: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    target_reps: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    workout_plan: Mapped["WorkoutPlan"] = relationship(back_populates="plan_exercises")
    exercise: Mapped["Exercise"] = relationship()


class WorkoutSession(Base):
    __tablename__ = "workout_sessions"
    __table_args__ = (
        Index("ix_workout_sessions_gym_id", "gym_id"),
        Index("ix_workout_sessions_member_id", "member_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    gym_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gyms.id", ondelete="CASCADE"), nullable=False
    )
    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    workout_plan_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workout_plans.id", ondelete="SET NULL"), nullable=True
    )
    status: Mapped[WorkoutSessionStatus] = mapped_column(
        Enum(WorkoutSessionStatus, name="workout_session_status"),
        nullable=False,
        default=WorkoutSessionStatus.IN_PROGRESS,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    member: Mapped["Member"] = relationship()
    exercise_logs: Mapped[list["ExerciseLog"]] = relationship(
        back_populates="workout_session", cascade="all, delete-orphan"
    )


class ExerciseLog(Base):
    """A single set performed within a workout session."""

    __tablename__ = "exercise_logs"
    __table_args__ = (Index("ix_exercise_logs_workout_session_id", "workout_session_id"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    workout_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("workout_sessions.id", ondelete="CASCADE"), nullable=False
    )
    exercise_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exercises.id", ondelete="RESTRICT"), nullable=False
    )
    set_number: Mapped[int] = mapped_column(Integer, nullable=False)
    reps: Mapped[int] = mapped_column(Integer, nullable=False)
    weight_kg: Mapped[Optional[float]] = mapped_column(Numeric(6, 2), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    workout_session: Mapped["WorkoutSession"] = relationship(back_populates="exercise_logs")
    exercise: Mapped["Exercise"] = relationship()
