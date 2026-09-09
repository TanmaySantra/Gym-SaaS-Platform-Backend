"""Membership plan + membership endpoints (sections 8/9/25). Mounted at /api/v1/memberships."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.dependencies import AuthContext, require_roles
from app.common.enums import UserRole
from app.common.pagination import PageParams, pagination_params
from app.common.responses import PaginatedData, PaginatedResponse, SuccessResponse
from app.core.database import get_db
from app.memberships import service
from app.memberships.schemas import MembershipCreate, MembershipOut, MembershipPlanCreate, MembershipPlanOut

router = APIRouter(dependencies=[Depends(require_roles(UserRole.OWNER))])


@router.post("/plans", response_model=SuccessResponse[MembershipPlanOut], status_code=201)
def create_plan(
    payload: MembershipPlanCreate, ctx: AuthContext = Depends(require_roles(UserRole.OWNER)),
    db: Session = Depends(get_db),
):
    plan = service.create_plan(
        db, actor_id=ctx.user.id, gym_id=ctx.gym_id, name=payload.name,
        duration_days=payload.duration_days, price=payload.price,
    )
    return SuccessResponse(data=MembershipPlanOut.model_validate(plan))


@router.get("/plans", response_model=PaginatedResponse[MembershipPlanOut])
def list_plans(
    params: PageParams = Depends(pagination_params), ctx: AuthContext = Depends(require_roles(UserRole.OWNER)),
    db: Session = Depends(get_db),
):
    data = service.list_plans(db, gym_id=ctx.gym_id, params=params)
    return PaginatedResponse(
        data=PaginatedData(
            items=[MembershipPlanOut.model_validate(p) for p in data.items],
            total=data.total, page=data.page, page_size=data.page_size, total_pages=data.total_pages,
        )
    )


@router.post("", response_model=SuccessResponse[MembershipOut], status_code=201)
def create_membership(
    payload: MembershipCreate, ctx: AuthContext = Depends(require_roles(UserRole.OWNER)),
    db: Session = Depends(get_db),
):
    membership = service.create_membership(
        db, actor_id=ctx.user.id, gym_id=ctx.gym_id, member_id=payload.member_id,
        plan_id=payload.plan_id, start_date=payload.start_date,
    )
    return SuccessResponse(data=MembershipOut.model_validate(membership))


@router.get("/{membership_id}", response_model=SuccessResponse[MembershipOut])
def get_membership(
    membership_id: uuid.UUID, ctx: AuthContext = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db)
):
    membership = service.get_membership(db, gym_id=ctx.gym_id, membership_id=membership_id)
    return SuccessResponse(data=MembershipOut.model_validate(membership))
