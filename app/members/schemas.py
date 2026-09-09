"""Schemas for member profiles (section 6/8)."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field


class MemberCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    date_of_birth: date | None = None


class MemberOut(BaseModel):
    id: uuid.UUID
    full_name: str
    phone: str | None
    date_of_birth: date | None
    is_linked: bool  # whether a MEMBER-role login has been linked yet
    created_at: datetime

    model_config = {"from_attributes": True}


class MemberLinkRequest(BaseModel):
    """Body for the public 'link my membership ID to a login' endpoint (section 8)."""

    membership_id_code: str = Field(min_length=1, max_length=32)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class MemberLinkResult(BaseModel):
    member_id: uuid.UUID
    user_id: uuid.UUID
    email: EmailStr
