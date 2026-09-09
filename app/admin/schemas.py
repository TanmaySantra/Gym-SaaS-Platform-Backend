"""Schemas for SUPER_ADMIN-only endpoints (sections 24/22/23)."""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.common.enums import GymStatus, SessionStatus


class GymCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9-]*$")


class GymAdminOut(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    status: GymStatus
    created_at: datetime

    model_config = {"from_attributes": True}


class GymDetailOut(GymAdminOut):
    owner_count: int
    member_count: int


class OwnerCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=1, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class OwnerOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    gym_id: uuid.UUID
    created_at: datetime

    model_config = {"from_attributes": True}


class PlatformStatsOut(BaseModel):
    total_gyms: int
    active_gyms: int
    total_owners: int
    total_members: int


class AuditLogOut(BaseModel):
    id: uuid.UUID
    actor_user_id: uuid.UUID | None
    gym_id: uuid.UUID | None
    action: str
    entity_type: str | None
    entity_id: str | None
    metadata_json: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}


class LoginSessionOut(BaseModel):
    id: uuid.UUID
    user_id: uuid.UUID
    gym_id: uuid.UUID | None
    login_at: datetime
    logout_at: datetime | None
    last_activity_at: datetime
    status: SessionStatus
    user_agent: str | None
    ip_address: str | None

    model_config = {"from_attributes": True}
