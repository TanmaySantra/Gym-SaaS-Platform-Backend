"""Schemas for progress_records (section 16). No field is mandatory except
that at least one measurement must be present — enforced in the service layer."""
from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class ProgressRecordCreate(BaseModel):
    weight_kg: Decimal | None = None
    height_cm: Decimal | None = None
    chest_cm: Decimal | None = None
    waist_cm: Decimal | None = None
    arms_cm: Decimal | None = None
    thighs_cm: Decimal | None = None


class ProgressRecordOut(BaseModel):
    id: uuid.UUID
    member_id: uuid.UUID
    weight_kg: Decimal | None
    height_cm: Decimal | None
    chest_cm: Decimal | None
    waist_cm: Decimal | None
    arms_cm: Decimal | None
    thighs_cm: Decimal | None
    recorded_at: datetime

    model_config = {"from_attributes": True}
