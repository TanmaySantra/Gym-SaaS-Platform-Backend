"""
Schemas for the AI insight engine (section 19).

MemberActivitySummary is the ONLY thing that reaches the model — never raw
DB rows, never SQL, never member PII beyond a first name for readability.
AIInsightResponse is what the model's output must validate against before
anything is trusted or persisted (section 37: "Never blindly trust raw
model output").
"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.common.enums import RiskLevel


class MemberActivitySummary(BaseModel):
    """The structured, pre-computed input handed to the model. Deliberately
    small and numeric/categorical — no free text from the DB is interpolated
    into the prompt, which also closes off prompt-injection via member notes."""

    member_first_name: str
    attendance_percentage_last_30_days: float = Field(ge=0, le=100)
    workouts_last_30_days: int = Field(ge=0)
    workouts_previous_30_days: int = Field(ge=0)
    weight_trend_kg: float | None = None  # positive = gained, negative = lost, None = no data
    membership_status: str
    membership_days_until_expiry: int | None = None


class AIInsightResponse(BaseModel):
    """
    The ONLY shape the model's output is allowed to take. Extra fields are
    silently dropped (section 37: "unexpected fields" must not break
    validation); missing/invalid required fields DO fail validation.
    Length caps guard against a hallucinated wall of text being stored and
    shown to an owner as if it were a normal-length insight.
    """

    model_config = {"extra": "ignore"}

    risk_level: RiskLevel
    insight: str = Field(min_length=1, max_length=500)
    reason: str = Field(min_length=1, max_length=1000)
    recommended_action: str = Field(min_length=1, max_length=500)


class AIInsightOut(BaseModel):
    id: uuid.UUID
    member_id: uuid.UUID
    risk_level: RiskLevel
    insight: str
    reason: str
    recommended_action: str
    created_at: datetime

    model_config = {"from_attributes": True}


class GenerateInsightAccepted(BaseModel):
    task_id: str
    member_id: uuid.UUID
