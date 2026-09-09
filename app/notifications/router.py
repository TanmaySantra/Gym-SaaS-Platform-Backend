"""Notification endpoints (section 21/25). Mounted at /api/v1/notifications."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.dependencies import AuthContext, get_current_user
from app.common.pagination import PageParams, pagination_params
from app.common.responses import PaginatedData, PaginatedResponse, SuccessResponse
from app.core.database import get_db
from app.notifications import service
from app.notifications.schemas import NotificationOut

router = APIRouter()


@router.get("", response_model=PaginatedResponse[NotificationOut])
def list_my_notifications(
    unread_only: bool = False, params: PageParams = Depends(pagination_params),
    ctx: AuthContext = Depends(get_current_user), db: Session = Depends(get_db),
):
    data = service.list_notifications_for_user(
        db, gym_id=ctx.gym_id, user_id=ctx.user.id, params=params, unread_only=unread_only
    )
    return PaginatedResponse(
        data=PaginatedData(
            items=[NotificationOut.model_validate(n) for n in data.items],
            total=data.total, page=data.page, page_size=data.page_size, total_pages=data.total_pages,
        )
    )


@router.post("/{notification_id}/read", response_model=SuccessResponse[NotificationOut])
def mark_read(
    notification_id: uuid.UUID, ctx: AuthContext = Depends(get_current_user), db: Session = Depends(get_db)
):
    notification = service.mark_as_read(db, gym_id=ctx.gym_id, user_id=ctx.user.id, notification_id=notification_id)
    return SuccessResponse(data=NotificationOut.model_validate(notification))


@router.post("/read-all", response_model=SuccessResponse[dict])
def mark_all_read(ctx: AuthContext = Depends(get_current_user), db: Session = Depends(get_db)):
    count = service.mark_all_as_read(db, gym_id=ctx.gym_id, user_id=ctx.user.id)
    return SuccessResponse(data={"marked_read": count})
