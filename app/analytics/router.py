"""Owner dashboard endpoints (section 13). Mounted at /api/v1/analytics."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.analytics import service
from app.analytics.schemas import DashboardMemberRow, DashboardSummaryOut
from app.common.dependencies import AuthContext, require_roles
from app.common.enums import UserRole
from app.common.pagination import PageParams, pagination_params
from app.common.responses import PaginatedData, PaginatedResponse, SuccessResponse
from app.core.database import get_db

router = APIRouter(dependencies=[Depends(require_roles(UserRole.OWNER))])


@router.get("/dashboard", response_model=SuccessResponse[DashboardSummaryOut])
def dashboard_summary(ctx: AuthContext = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db)):
    summary = service.get_owner_dashboard_summary(db, gym_id=ctx.gym_id)
    return SuccessResponse(data=DashboardSummaryOut.model_validate(summary))


@router.get("/dashboard/members", response_model=PaginatedResponse[DashboardMemberRow])
def dashboard_member_list(
    params: PageParams = Depends(pagination_params), ctx: AuthContext = Depends(require_roles(UserRole.OWNER)),
    db: Session = Depends(get_db),
):
    data = service.get_dashboard_member_rows(db, gym_id=ctx.gym_id, params=params)
    return PaginatedResponse(
        data=PaginatedData(
            items=[DashboardMemberRow.model_validate(r) for r in data.items],
            total=data.total, page=data.page, page_size=data.page_size, total_pages=data.total_pages,
        )
    )
