"""AI insight endpoints. Mounted at /api/v1/ai."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.ai import service
from app.ai.schemas import AIInsightOut
from app.common.dependencies import AuthContext, get_current_member, require_roles
from app.common.enums import UserRole
from app.common.pagination import PageParams, pagination_params
from app.common.responses import PaginatedData, PaginatedResponse, SuccessResponse
from app.core.database import get_db
from app.members.models import Member
from app.members.service import get_member as get_member_scoped

router = APIRouter()


class GenerateInsightRequest(BaseModel):
    member_id: uuid.UUID


@router.post(
    "/insights/generate", response_model=SuccessResponse[AIInsightOut], status_code=201,
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)
def generate_insight(
    payload: GenerateInsightRequest, ctx: AuthContext = Depends(require_roles(UserRole.OWNER)),
    db: Session = Depends(get_db),
):
    """
    Synchronous, owner-triggered generation for one member. Confirms the
    member belongs to the caller's gym first (section 33/34), then runs the
    full AI pipeline. A provider/validation failure surfaces as a normal
    AppError (502, distinct error code) rather than crashing — the same
    safety property the Celery task relies on (section 20).
    """
    get_member_scoped(db, gym_id=ctx.gym_id, member_id=payload.member_id)
    insight = service.generate_insight_for_member(db, gym_id=ctx.gym_id, member_id=payload.member_id)
    return SuccessResponse(data=AIInsightOut.model_validate(insight))


@router.get("/insights/me", response_model=PaginatedResponse[AIInsightOut])
def my_insights(
    params: PageParams = Depends(pagination_params), member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    data = service.list_insights_for_member(db, gym_id=member.gym_id, member_id=member.id, params=params)
    return PaginatedResponse(
        data=PaginatedData(
            items=[AIInsightOut.model_validate(i) for i in data.items],
            total=data.total, page=data.page, page_size=data.page_size, total_pages=data.total_pages,
        )
    )


@router.get(
    "/insights/members/{member_id}", response_model=PaginatedResponse[AIInsightOut],
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)
def member_insights(
    member_id: uuid.UUID, params: PageParams = Depends(pagination_params),
    ctx: AuthContext = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db),
):
    get_member_scoped(db, gym_id=ctx.gym_id, member_id=member_id)
    data = service.list_insights_for_member(db, gym_id=ctx.gym_id, member_id=member_id, params=params)
    return PaginatedResponse(
        data=PaginatedData(
            items=[AIInsightOut.model_validate(i) for i in data.items],
            total=data.total, page=data.page, page_size=data.page_size, total_pages=data.total_pages,
        )
    )


@router.get(
    "/insights", response_model=PaginatedResponse[AIInsightOut], dependencies=[Depends(require_roles(UserRole.OWNER))]
)
def gym_insights_feed(
    params: PageParams = Depends(pagination_params), ctx: AuthContext = Depends(require_roles(UserRole.OWNER)),
    db: Session = Depends(get_db),
):
    data = service.list_insights_for_gym(db, gym_id=ctx.gym_id, params=params)
    return PaginatedResponse(
        data=PaginatedData(
            items=[AIInsightOut.model_validate(i) for i in data.items],
            total=data.total, page=data.page, page_size=data.page_size, total_pages=data.total_pages,
        )
    )
