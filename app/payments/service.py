"""Payment service layer (section 18). Recording a payment is the one
user-facing action that can move a membership back to ACTIVE (section 9)."""
from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.audit import log_audit_event
from app.common.enums import MembershipStatus
from app.common.pagination import PageParams, paginate
from app.common.responses import PaginatedData
from app.core.exceptions import ConflictError, NotFoundError
from app.memberships.lifecycle import reactivate_with_payment
from app.memberships.models import Membership
from app.payments.models import Payment, Expense
from app.common.enums import PaymentStatus


def record_payment(
    db: Session, *, actor_id: uuid.UUID, gym_id: uuid.UUID, membership_id: uuid.UUID, amount, payment_date: date | None
) -> Payment:
    membership = db.scalar(select(Membership).where(Membership.id == membership_id, Membership.gym_id == gym_id))
    if membership is None:
        raise NotFoundError("Membership not found.", code="MEMBERSHIP_NOT_FOUND")

    if membership.status in (MembershipStatus.CANCELLED, MembershipStatus.EXPIRED):
        raise ConflictError(
            f"Cannot record a payment for a {membership.status.value.lower()} membership. "
            "Create a new membership instead.",
            code="MEMBERSHIP_TERMINAL_STATE",
        )

    resolved_date = payment_date or date.today()
    status_before = membership.status

    payment = Payment(
        gym_id=gym_id, member_id=membership.member_id, membership_id=membership.id,
        amount=amount, payment_date=resolved_date, status=PaymentStatus.PAID,
    )
    db.add(payment)
    db.flush()

    plan_duration_days = membership.plan.duration_days
    result = reactivate_with_payment(membership, plan_duration_days=plan_duration_days, payment_date=resolved_date)

    log_audit_event(
        db, actor_user_id=actor_id, gym_id=gym_id, action="PAYMENT_RECORDED",
        entity_type="payment", entity_id=str(payment.id),
        metadata={"membership_id": str(membership.id), "amount": str(amount)},
    )
    if result.changed:
        log_audit_event(
            db, actor_user_id=actor_id, gym_id=gym_id, action="MEMBERSHIP_STATUS_CHANGED",
            entity_type="membership", entity_id=str(membership.id),
            metadata={"from": status_before.value, "to": membership.status.value, "source": "payment"},
        )

    db.commit()
    db.refresh(payment)
    return payment


def list_payments(db: Session, *, gym_id: uuid.UUID, params: PageParams) -> PaginatedData:
    stmt = select(Payment).where(Payment.gym_id == gym_id).order_by(Payment.created_at.desc())
    return paginate(db, stmt, params)


def get_payment(db: Session, *, gym_id: uuid.UUID, payment_id: uuid.UUID) -> Payment:
    payment = db.scalar(select(Payment).where(Payment.id == payment_id, Payment.gym_id == gym_id))
    if payment is None:
        raise NotFoundError("Payment not found.", code="PAYMENT_NOT_FOUND")
    return payment


def record_expense(
    db: Session, *, actor_id: uuid.UUID, gym_id: uuid.UUID, category: str, amount, expense_date: date | None,
    description: str | None,
) -> Expense:
    resolved_date = expense_date or date.today()
    expense = Expense(gym_id=gym_id, category=category, amount=amount, date=resolved_date, description=description)
    db.add(expense)
    db.flush()

    log_audit_event(
        db, actor_user_id=actor_id, gym_id=gym_id, action="EXPENSE_RECORDED",
        entity_type="expense", entity_id=str(expense.id), metadata={"category": category, "amount": str(amount)},
    )
    db.commit()
    db.refresh(expense)
    return expense


def list_expenses(db: Session, *, gym_id: uuid.UUID, params: PageParams) -> PaginatedData:
    stmt = select(Expense).where(Expense.gym_id == gym_id).order_by(Expense.date.desc())
    return paginate(db, stmt, params)


def get_finance_summary(db: Session, *, gym_id: uuid.UUID) -> dict:
    """
    Basic finance dashboard numbers (section 13/18). Deliberately simple:
    total revenue from PAID payments, total expenses, net profit, and a count
    of memberships currently owed money (PAYMENT_DUE or RESTRICTED) as a
    proxy for "outstanding payments" — V1 has no invoicing concept beyond
    the membership status itself.
    """
    from sqlalchemy import func

    total_revenue = db.scalar(
        select(func.coalesce(func.sum(Payment.amount), 0)).where(
            Payment.gym_id == gym_id, Payment.status == PaymentStatus.PAID
        )
    )
    total_expenses = db.scalar(select(func.coalesce(func.sum(Expense.amount), 0)).where(Expense.gym_id == gym_id))
    outstanding_count = db.scalar(
        select(func.count()).select_from(Membership).where(
            Membership.gym_id == gym_id,
            Membership.status.in_([MembershipStatus.PAYMENT_DUE, MembershipStatus.RESTRICTED]),
        )
    ) or 0

    return {
        "total_revenue": total_revenue,
        "total_expenses": total_expenses,
        "net_profit": total_revenue - total_expenses,
        "outstanding_payments_count": outstanding_count,
    }
