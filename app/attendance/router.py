"""Attendance endpoints (sections 13/14/17/25). Mounted at /api/v1/attendance."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.attendance import service
from app.attendance.schemas import AttendanceCreate, AttendanceOut, AttendanceSummaryOut
from app.common.dependencies import AuthContext, get_current_member, require_roles
from app.common.enums import UserRole
from app.common.pagination import PageParams, pagination_params
from app.common.responses import PaginatedData, PaginatedResponse, SuccessResponse
from app.core.database import get_db
from app.members.models import Member

router = APIRouter()


@router.post(
    "", response_model=SuccessResponse[AttendanceOut], status_code=201,
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)
def record_attendance(
    payload: AttendanceCreate, ctx: AuthContext = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db)
):
    record = service.record_attendance(
        db, actor_id=ctx.user.id, gym_id=ctx.gym_id, member_id=payload.member_id, attendance_date=payload.date,
        check_in=payload.check_in, check_out=payload.check_out,
    )
    return SuccessResponse(data=AttendanceOut.model_validate(record))


@router.get("/me", response_model=PaginatedResponse[AttendanceOut])
def list_my_attendance(
    params: PageParams = Depends(pagination_params), member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    data = service.list_attendance_for_member(db, gym_id=member.gym_id, member_id=member.id, params=params)
    return PaginatedResponse(
        data=PaginatedData(
            items=[AttendanceOut.model_validate(a) for a in data.items],
            total=data.total, page=data.page, page_size=data.page_size, total_pages=data.total_pages,
        )
    )


@router.get("/me/summary", response_model=SuccessResponse[AttendanceSummaryOut])
def my_attendance_summary(member: Member = Depends(get_current_member), db: Session = Depends(get_db)):
    summary = service.get_attendance_summary(db, gym_id=member.gym_id, member_id=member.id)
    return SuccessResponse(data=AttendanceSummaryOut.model_validate(summary))


@router.get(
    "/members/{member_id}", response_model=PaginatedResponse[AttendanceOut],
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)
def get_member_attendance(
    member_id: uuid.UUID, params: PageParams = Depends(pagination_params),
    ctx: AuthContext = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db),
):
    from app.members.service import get_member as get_member_scoped

    get_member_scoped(db, gym_id=ctx.gym_id, member_id=member_id)
    data = service.list_attendance_for_member(db, gym_id=ctx.gym_id, member_id=member_id, params=params)
    return PaginatedResponse(
        data=PaginatedData(
            items=[AttendanceOut.model_validate(a) for a in data.items],
            total=data.total, page=data.page, page_size=data.page_size, total_pages=data.total_pages,
        )
    )
