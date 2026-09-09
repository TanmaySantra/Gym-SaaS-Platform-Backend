"""Progress service layer (section 16)."""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.pagination import PageParams, paginate
from app.common.responses import PaginatedData
from app.core.exceptions import AppError
from app.memberships.service import assert_not_restricted
from app.progress.models import ProgressRecord


class NoMeasurementProvidedError(AppError):
    code = "NO_MEASUREMENT_PROVIDED"

    def __init__(self):
        super().__init__("At least one measurement must be provided.", code=self.code, status_code=422)


_MEASUREMENT_FIELDS = ("weight_kg", "height_cm", "chest_cm", "waist_cm", "arms_cm", "thighs_cm")


def create_progress_record(db: Session, *, gym_id: uuid.UUID, member_id: uuid.UUID, values: dict) -> ProgressRecord:
    if all(values.get(f) is None for f in _MEASUREMENT_FIELDS):
        raise NoMeasurementProvidedError()

    assert_not_restricted(db, gym_id=gym_id, member_id=member_id)

    record = ProgressRecord(gym_id=gym_id, member_id=member_id, **{f: values.get(f) for f in _MEASUREMENT_FIELDS})
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def list_progress_for_member(db: Session, *, gym_id: uuid.UUID, member_id: uuid.UUID, params: PageParams) -> PaginatedData:
    """
    Used by BOTH the member's own history view and the owner's per-member
    progress view (section 13/16: "Owner should be able to see the same
    progress data for members belonging to their gym") — callers just supply
    the right member_id, gym_id scoping is identical either way.
    """
    stmt = (
        select(ProgressRecord)
        .where(ProgressRecord.gym_id == gym_id, ProgressRecord.member_id == member_id)
        .order_by(ProgressRecord.recorded_at.desc())
    )
    return paginate(db, stmt, params)
