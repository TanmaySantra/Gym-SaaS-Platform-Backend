"""Request/response schemas for the auth module. Section 7."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field

from app.common.enums import UserRole


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class SignupRequest(BaseModel):
    membership_id_code: str = Field(min_length=1, max_length=32)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"


class SignupResponse(BaseModel):
    user: "CurrentUserOut"
    tokens: TokenResponse


class AccessTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class CurrentUserOut(BaseModel):
    id: uuid.UUID
    email: EmailStr
    full_name: str
    role: UserRole
    gym_id: uuid.UUID | None

    model_config = {"from_attributes": True}
