"""Payment endpoints (sections 18/25). Mounted at /api/v1/payments."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.dependencies import AuthContext, require_roles
from app.common.enums import UserRole
from app.common.pagination import PageParams, pagination_params
from app.common.responses import PaginatedData, PaginatedResponse, SuccessResponse
from app.core.database import get_db
from app.payments import service
from app.payments.schemas import ExpenseCreate, ExpenseOut, FinanceSummaryOut, PaymentCreate, PaymentOut

router = APIRouter(dependencies=[Depends(require_roles(UserRole.OWNER))])


@router.post("", response_model=SuccessResponse[PaymentOut], status_code=201)
def record_payment(
    payload: PaymentCreate, ctx: AuthContext = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db)
):
    payment = service.record_payment(
        db, actor_id=ctx.user.id, gym_id=ctx.gym_id, membership_id=payload.membership_id,
        amount=payload.amount, payment_date=payload.payment_date,
    )
    return SuccessResponse(data=PaymentOut.model_validate(payment))


@router.get("", response_model=PaginatedResponse[PaymentOut])
def list_payments(
    params: PageParams = Depends(pagination_params), ctx: AuthContext = Depends(require_roles(UserRole.OWNER)),
    db: Session = Depends(get_db),
):
    data = service.list_payments(db, gym_id=ctx.gym_id, params=params)
    return PaginatedResponse(
        data=PaginatedData(
            items=[PaymentOut.model_validate(p) for p in data.items],
            total=data.total, page=data.page, page_size=data.page_size, total_pages=data.total_pages,
        )
    )


@router.post("/expenses", response_model=SuccessResponse[ExpenseOut], status_code=201)
def record_expense(
    payload: ExpenseCreate, ctx: AuthContext = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db)
):
    expense = service.record_expense(
        db, actor_id=ctx.user.id, gym_id=ctx.gym_id, category=payload.category, amount=payload.amount,
        expense_date=payload.date, description=payload.description,
    )
    return SuccessResponse(data=ExpenseOut.model_validate(expense))


@router.get("/expenses", response_model=PaginatedResponse[ExpenseOut])
def list_expenses(
    params: PageParams = Depends(pagination_params), ctx: AuthContext = Depends(require_roles(UserRole.OWNER)),
    db: Session = Depends(get_db),
):
    data = service.list_expenses(db, gym_id=ctx.gym_id, params=params)
    return PaginatedResponse(
        data=PaginatedData(
            items=[ExpenseOut.model_validate(e) for e in data.items],
            total=data.total, page=data.page, page_size=data.page_size, total_pages=data.total_pages,
        )
    )


@router.get("/finance/summary", response_model=SuccessResponse[FinanceSummaryOut])
def finance_summary(ctx: AuthContext = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db)):
    summary = service.get_finance_summary(db, gym_id=ctx.gym_id)
    return SuccessResponse(data=FinanceSummaryOut.model_validate(summary))


@router.get("/{payment_id}", response_model=SuccessResponse[PaymentOut])
def get_payment(
    payment_id: uuid.UUID, ctx: AuthContext = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db)
):
    payment = service.get_payment(db, gym_id=ctx.gym_id, payment_id=payment_id)
    return SuccessResponse(data=PaymentOut.model_validate(payment))
