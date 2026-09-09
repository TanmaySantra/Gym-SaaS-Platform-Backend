"""Schemas for gym data as seen by an OWNER looking at their own gym."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.common.enums import GymStatus


class GymOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: GymStatus
    created_at: datetime

    model_config = {"from_attributes": True}
