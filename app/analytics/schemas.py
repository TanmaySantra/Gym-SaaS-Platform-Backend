"""Schemas for the owner dashboard (section 13)."""
from __future__ import annotations

import uuid
from decimal import Decimal


from pydantic import BaseModel


class DashboardSummaryOut(BaseModel):
    total_members: int
    active_members: int
    payment_due_members: int
    restricted_members: int
    expiring_within_7_days: int
    attendance_today_count: int
    total_revenue: Decimal
    total_expenses: Decimal
    net_profit: Decimal
    recent_ai_insights_count: int


class DashboardMemberRow(BaseModel):
    member_id: uuid.UUID
    full_name: str
    membership_id_code: str | None
    membership_status: str | None
    attendance_percentage_last_30_days: float
    progress_trend: str  # "up" | "down" | "stable" | "no data"
