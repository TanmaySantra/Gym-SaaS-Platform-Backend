"""Schemas for the payments module (section 18)."""
from __future__ import annotations

import uuid
import datetime as dt
from decimal import Decimal

from pydantic import BaseModel, Field

from app.common.enums import PaymentStatus


class PaymentCreate(BaseModel):
    membership_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    payment_date: dt.date | None = None  # defaults to today


class PaymentOut(BaseModel):
    id: uuid.UUID
    membership_id: uuid.UUID
    member_id: uuid.UUID
    amount: Decimal
    payment_date: dt.date
    status: PaymentStatus
    created_at: dt.datetime

    model_config = {"from_attributes": True}


class ExpenseCreate(BaseModel):
    category: str = Field(min_length=1, max_length=100)
    amount: Decimal = Field(gt=0)
    date: dt.date | None = None  # defaults to today
    description: str | None = Field(default=None, max_length=1000)


class ExpenseOut(BaseModel):
    id: uuid.UUID
    category: str
    amount: Decimal
    date: dt.date
    description: str | None
    created_at: dt.datetime

    model_config = {"from_attributes": True}


class FinanceSummaryOut(BaseModel):
    total_revenue: Decimal
    total_expenses: Decimal
    net_profit: Decimal
    outstanding_payments_count: int
