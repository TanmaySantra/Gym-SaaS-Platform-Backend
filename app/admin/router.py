"""Platform-admin endpoints (section 24/25). Mounted at /api/v1/admin. Every
route here requires SUPER_ADMIN — enforced via require_roles, not by convention."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.admin import service
from app.admin.schemas import (
    AuditLogOut,
    GymAdminOut,
    GymCreate,
    GymDetailOut,
    LoginSessionOut,
    OwnerCreate,
    OwnerOut,
    PlatformStatsOut,
)
from app.common.dependencies import AuthContext, require_roles
from app.common.enums import UserRole
from app.common.pagination import PageParams, pagination_params
from app.common.responses import PaginatedData, PaginatedResponse, SuccessResponse
from app.core.database import get_db

router = APIRouter(dependencies=[Depends(require_roles(UserRole.SUPER_ADMIN))])


def _paginated_response(data: PaginatedData, schema) -> PaginatedResponse:
    return PaginatedResponse(
        data=PaginatedData(
            items=[schema.model_validate(item) for item in data.items],
            total=data.total,
            page=data.page,
            page_size=data.page_size,
            total_pages=data.total_pages,
        )
    )


@router.post("/gyms", response_model=SuccessResponse[GymAdminOut], status_code=201)
def create_gym(
    payload: GymCreate, ctx: AuthContext = Depends(require_roles(UserRole.SUPER_ADMIN)), db: Session = Depends(get_db)
):
    gym = service.create_gym(db, actor_id=ctx.user.id, name=payload.name, slug=payload.slug)
    return SuccessResponse(data=GymAdminOut.model_validate(gym))


@router.get("/gyms", response_model=PaginatedResponse[GymAdminOut])
def list_gyms(params: PageParams = Depends(pagination_params), db: Session = Depends(get_db)):
    data = service.list_gyms(db, params)
    return _paginated_response(data, GymAdminOut)


@router.get("/gyms/{gym_id}", response_model=SuccessResponse[GymDetailOut])
def get_gym(gym_id: uuid.UUID, db: Session = Depends(get_db)):
    result = service.get_gym_detail(db, gym_id=gym_id)
    detail = GymDetailOut.model_validate(
        {**GymAdminOut.model_validate(result["gym"]).model_dump(),
         "owner_count": result["owner_count"], "member_count": result["member_count"]}
    )
    return SuccessResponse(data=detail)


@router.post("/gyms/{gym_id}/suspend", response_model=SuccessResponse[GymAdminOut])
def suspend_gym(
    gym_id: uuid.UUID, ctx: AuthContext = Depends(require_roles(UserRole.SUPER_ADMIN)), db: Session = Depends(get_db)
):
    gym = service.suspend_gym(db, actor_id=ctx.user.id, gym_id=gym_id)
    return SuccessResponse(data=GymAdminOut.model_validate(gym))


@router.post("/gyms/{gym_id}/activate", response_model=SuccessResponse[GymAdminOut])
def activate_gym(
    gym_id: uuid.UUID, ctx: AuthContext = Depends(require_roles(UserRole.SUPER_ADMIN)), db: Session = Depends(get_db)
):
    gym = service.activate_gym(db, actor_id=ctx.user.id, gym_id=gym_id)
    return SuccessResponse(data=GymAdminOut.model_validate(gym))


@router.post("/gyms/{gym_id}/owners", response_model=SuccessResponse[OwnerOut], status_code=201)
def create_owner(
    gym_id: uuid.UUID,
    payload: OwnerCreate,
    ctx: AuthContext = Depends(require_roles(UserRole.SUPER_ADMIN)),
    db: Session = Depends(get_db),
):
    owner = service.create_owner(
        db, actor_id=ctx.user.id, gym_id=gym_id, email=payload.email, full_name=payload.full_name,
        password=payload.password,
    )
    return SuccessResponse(data=OwnerOut.model_validate(owner))


@router.get("/stats", response_model=SuccessResponse[PlatformStatsOut])
def get_platform_stats(db: Session = Depends(get_db)):
    return SuccessResponse(data=service.platform_stats(db))


@router.get("/audit-logs", response_model=PaginatedResponse[AuditLogOut])
def list_audit_logs(params: PageParams = Depends(pagination_params), db: Session = Depends(get_db)):
    data = service.list_audit_logs(db, params)
    return _paginated_response(data, AuditLogOut)


@router.get("/login-sessions", response_model=PaginatedResponse[LoginSessionOut])
def list_login_sessions(
    user_id: uuid.UUID | None = None,
    params: PageParams = Depends(pagination_params),
    db: Session = Depends(get_db),
):
    data = service.list_login_sessions(db, params, user_id=user_id)
    return _paginated_response(data, LoginSessionOut)
