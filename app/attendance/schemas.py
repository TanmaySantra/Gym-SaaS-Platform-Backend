"""Schemas for attendance (section 17). Manual owner-recorded only in V1."""
from __future__ import annotations

import uuid
import datetime as dt

from pydantic import BaseModel


class AttendanceCreate(BaseModel):
    member_id: uuid.UUID
    date: dt.date | None = None  # defaults to today
    check_in: dt.datetime | None = None
    check_out: dt.datetime | None = None


class AttendanceOut(BaseModel):
    id: uuid.UUID
    member_id: uuid.UUID
    date: dt.date
    check_in: dt.datetime | None
    check_out: dt.datetime | None
    created_at: dt.datetime

    model_config = {"from_attributes": True}


class AttendanceSummaryOut(BaseModel):
    member_id: uuid.UUID
    total_days_recorded: int
    days_present_last_30: int
    attendance_percentage_last_30: float
