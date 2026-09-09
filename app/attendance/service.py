"""Attendance service layer (section 17). Manual, owner-recorded only in V1
— no QR/biometric."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.attendance.models import Attendance
from app.common.audit import log_audit_event
from app.common.pagination import PageParams, paginate
from app.common.responses import PaginatedData
from app.core.exceptions import ConflictError, NotFoundError
from app.members.service import get_member


def record_attendance(
    db: Session, *, actor_id: uuid.UUID, gym_id: uuid.UUID, member_id: uuid.UUID, attendance_date: date | None,
    check_in, check_out,
) -> Attendance:
    # Validates member_id actually belongs to this gym BEFORE creating the
    # row — without this, an owner could pass another gym's member_id
    # alongside their own (correct) gym_id and create a cross-tenant record
    # (section 33/34: IDOR via request body).
    get_member(db, gym_id=gym_id, member_id=member_id)

    resolved_date = attendance_date or date.today()
    record = Attendance(
        gym_id=gym_id, member_id=member_id, date=resolved_date, check_in=check_in, check_out=check_out
    )
    db.add(record)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise ConflictError(
            f"Attendance for this member on {resolved_date} has already been recorded.",
            code="ATTENDANCE_ALREADY_RECORDED",
        ) from exc

    log_audit_event(
        db, actor_user_id=actor_id, gym_id=gym_id, action="ATTENDANCE_RECORDED",
        entity_type="attendance", entity_id=str(record.id), metadata={"member_id": str(member_id), "date": str(resolved_date)},
    )
    db.commit()
    db.refresh(record)
    return record


def list_attendance_for_member(db: Session, *, gym_id: uuid.UUID, member_id: uuid.UUID, params: PageParams) -> PaginatedData:
    stmt = (
        select(Attendance)
        .where(Attendance.gym_id == gym_id, Attendance.member_id == member_id)
        .order_by(Attendance.date.desc())
    )
    return paginate(db, stmt, params)


def get_attendance_summary(db: Session, *, gym_id: uuid.UUID, member_id: uuid.UUID) -> dict:
    total = db.scalar(
        select(Attendance.id).where(Attendance.gym_id == gym_id, Attendance.member_id == member_id)
    )
    all_rows = list(
        db.scalars(select(Attendance).where(Attendance.gym_id == gym_id, Attendance.member_id == member_id))
    )
    cutoff = date.today() - timedelta(days=30)
    present_last_30 = sum(1 for a in all_rows if a.date >= cutoff)
    return {
        "member_id": member_id,
        "total_days_recorded": len(all_rows),
        "days_present_last_30": present_last_30,
        "attendance_percentage_last_30": round((present_last_30 / 30) * 100, 1),
    }
