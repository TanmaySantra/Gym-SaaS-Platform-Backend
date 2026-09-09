"""Auth endpoints (section 7 / 25). Mounted at /api/v1/auth."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.auth import service
from app.auth.schemas import (
    AccessTokenResponse,
    CurrentUserOut,
    LoginRequest,
    RefreshRequest,
    SignupRequest,
    SignupResponse,
    TokenResponse,
)
from app.common.dependencies import AuthContext, get_current_user
from app.common.responses import SuccessResponse
from app.core.database import get_db

router = APIRouter()


@router.post("/signup", response_model=SuccessResponse[SignupResponse], status_code=201)
def signup(payload: SignupRequest, request: Request, db: Session = Depends(get_db)):
    result = service.signup(
        db,
        membership_id_code=payload.membership_id_code,
        email=payload.email,
        password=payload.password,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    return SuccessResponse(data=result)


@router.post("/login", response_model=SuccessResponse[TokenResponse])
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    tokens = service.login(
        db,
        email=payload.email,
        password=payload.password,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    return SuccessResponse(data=tokens)


@router.post("/refresh", response_model=SuccessResponse[AccessTokenResponse])
def refresh(payload: RefreshRequest, db: Session = Depends(get_db)):
    access_token = service.refresh_access_token(db, refresh_token=payload.refresh_token)
    return SuccessResponse(data=AccessTokenResponse(access_token=access_token))


@router.post("/logout", response_model=SuccessResponse[dict])
def logout(ctx: AuthContext = Depends(get_current_user), db: Session = Depends(get_db)):
    service.logout(db, session_id=ctx.session_id, user_id=ctx.user.id)
    return SuccessResponse(data={"logged_out": True})


@router.get("/me", response_model=SuccessResponse[CurrentUserOut])
def me(ctx: AuthContext = Depends(get_current_user)):
    return SuccessResponse(data=CurrentUserOut.model_validate(ctx.user))
