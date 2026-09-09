"""Schemas for exercises, workout plans, sessions, and exercise logs (section 15)."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.common.enums import WorkoutSessionStatus


class ExerciseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    muscle_group: str | None = Field(default=None, max_length=100)


class ExerciseOut(BaseModel):
    id: uuid.UUID
    name: str
    muscle_group: str | None

    model_config = {"from_attributes": True}


class WorkoutSessionCreate(BaseModel):
    workout_plan_id: uuid.UUID | None = None


class WorkoutSessionOut(BaseModel):
    id: uuid.UUID
    member_id: uuid.UUID
    workout_plan_id: uuid.UUID | None
    status: WorkoutSessionStatus
    started_at: datetime
    completed_at: datetime | None

    model_config = {"from_attributes": True}


class ExerciseLogCreate(BaseModel):
    exercise_id: uuid.UUID
    set_number: int = Field(gt=0, le=50)
    reps: int = Field(gt=0, le=1000)
    weight_kg: Decimal | None = Field(default=None, ge=0)
    notes: str | None = Field(default=None, max_length=1000)


class ExerciseLogOut(BaseModel):
    id: uuid.UUID
    workout_session_id: uuid.UUID
    exercise_id: uuid.UUID
    set_number: int
    reps: int
    weight_kg: Decimal | None
    notes: str | None
    created_at: datetime

    model_config = {"from_attributes": True}
