"""Schemas for the notifications module (section 21)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel

from app.common.enums import NotificationType


class NotificationOut(BaseModel):
    id: uuid.UUID
    type: NotificationType
    title: str
    message: str
    read: bool
    created_at: datetime

    model_config = {"from_attributes": True}
