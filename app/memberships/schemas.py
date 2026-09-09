"""Schemas for membership_plans and memberships (sections 8/9)."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.common.enums import MembershipStatus


class MembershipPlanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    duration_days: int = Field(gt=0, le=3650)
    price: Decimal = Field(gt=0)


class MembershipPlanOut(BaseModel):
    id: uuid.UUID
    name: str
    duration_days: int
    price: Decimal
    created_at: datetime

    model_config = {"from_attributes": True}


class MembershipCreate(BaseModel):
    member_id: uuid.UUID
    plan_id: uuid.UUID
    start_date: date | None = None  # defaults to today in the service layer


class MembershipOut(BaseModel):
    id: uuid.UUID
    member_id: uuid.UUID
    plan_id: uuid.UUID
    membership_id_code: str
    is_linked: bool
    status: MembershipStatus
    start_date: date
    end_date: date
    created_at: datetime

    model_config = {"from_attributes": True}
