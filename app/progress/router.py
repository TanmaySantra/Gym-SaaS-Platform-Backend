"""Progress endpoints (sections 13/14/16/25). Mounted at /api/v1/progress."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.dependencies import AuthContext, get_current_member, require_roles
from app.common.enums import UserRole
from app.common.pagination import PageParams, pagination_params
from app.common.responses import PaginatedData, PaginatedResponse, SuccessResponse
from app.core.database import get_db
from app.members import service as members_service
from app.members.models import Member
from app.progress import service
from app.progress.schemas import ProgressRecordCreate, ProgressRecordOut

router = APIRouter()


@router.post("", response_model=SuccessResponse[ProgressRecordOut], status_code=201)
def create_progress_record(
    payload: ProgressRecordCreate, member: Member = Depends(get_current_member), db: Session = Depends(get_db)
):
    record = service.create_progress_record(db, gym_id=member.gym_id, member_id=member.id, values=payload.model_dump())
    return SuccessResponse(data=ProgressRecordOut.model_validate(record))


@router.get("", response_model=PaginatedResponse[ProgressRecordOut])
def list_my_progress(
    params: PageParams = Depends(pagination_params), member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    data = service.list_progress_for_member(db, gym_id=member.gym_id, member_id=member.id, params=params)
    return PaginatedResponse(
        data=PaginatedData(
            items=[ProgressRecordOut.model_validate(r) for r in data.items],
            total=data.total, page=data.page, page_size=data.page_size, total_pages=data.total_pages,
        )
    )


@router.get(
    "/members/{member_id}", response_model=PaginatedResponse[ProgressRecordOut],
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)
def get_member_progress(
    member_id: uuid.UUID, params: PageParams = Depends(pagination_params),
    ctx: AuthContext = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db),
):
    # Confirms the member belongs to this owner's gym before returning any
    # data — 404s cleanly for a cross-tenant member_id (section 34).
    members_service.get_member(db, gym_id=ctx.gym_id, member_id=member_id)
    data = service.list_progress_for_member(db, gym_id=ctx.gym_id, member_id=member_id, params=params)
    return PaginatedResponse(
        data=PaginatedData(
            items=[ProgressRecordOut.model_validate(r) for r in data.items],
            total=data.total, page=data.page, page_size=data.page_size, total_pages=data.total_pages,
        )
    )
