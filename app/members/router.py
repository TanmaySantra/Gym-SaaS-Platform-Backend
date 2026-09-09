"""Member endpoints (sections 6/8/25). Mounted at /api/v1/members."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.dependencies import AuthContext, require_roles
from app.common.enums import UserRole
from app.common.pagination import PageParams, pagination_params
from app.common.responses import PaginatedData, PaginatedResponse, SuccessResponse
from app.core.database import get_db
from app.members import service
from app.members.schemas import MemberCreate, MemberLinkRequest, MemberLinkResult, MemberOut

router = APIRouter()


@router.post(
    "",
    response_model=SuccessResponse[MemberOut],
    status_code=201,
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)
def create_member(
    payload: MemberCreate, ctx: AuthContext = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db)
):
    member = service.create_member(
        db, actor_id=ctx.user.id, gym_id=ctx.gym_id, full_name=payload.full_name,
        phone=payload.phone, date_of_birth=payload.date_of_birth,
    )
    return SuccessResponse(data=MemberOut.model_validate(member))


@router.get("", response_model=PaginatedResponse[MemberOut], dependencies=[Depends(require_roles(UserRole.OWNER))])
def list_members(
    params: PageParams = Depends(pagination_params),
    ctx: AuthContext = Depends(require_roles(UserRole.OWNER)),
    db: Session = Depends(get_db),
):
    data = service.list_members(db, gym_id=ctx.gym_id, params=params)
    return PaginatedResponse(
        data=PaginatedData(
            items=[MemberOut.model_validate(m) for m in data.items],
            total=data.total, page=data.page, page_size=data.page_size, total_pages=data.total_pages,
        )
    )


@router.get(
    "/{member_id}", response_model=SuccessResponse[MemberOut], dependencies=[Depends(require_roles(UserRole.OWNER))]
)
def get_member(
    member_id: uuid.UUID, ctx: AuthContext = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db)
):
    member = service.get_member(db, gym_id=ctx.gym_id, member_id=member_id)
    return SuccessResponse(data=MemberOut.model_validate(member))


@router.post("/link", response_model=SuccessResponse[MemberLinkResult])
def link_membership(payload: MemberLinkRequest, db: Session = Depends(get_db)):
    """
    Public endpoint (no auth) — a prospective member uses the code the owner
    gave them plus a chosen email/password to create their own login.
    """
    member, user = service.link_membership(
        db, membership_id_code=payload.membership_id_code, email=payload.email, password=payload.password
    )
    return SuccessResponse(data=MemberLinkResult(member_id=member.id, user_id=user.id, email=user.email))
