"""Membership plan + membership service layer, strictly gym-scoped (section 5)."""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.audit import log_audit_event
from app.common.pagination import PageParams, paginate
from app.common.responses import PaginatedData
from app.core.config import settings
from app.core.exceptions import MembershipRestrictedError, NotFoundError
from app.gyms.models import Gym
from app.members.models import Member
from app.memberships.lifecycle import apply_expiry_check, apply_payment_due_check, blocks_new_tracking
from app.memberships.models import Membership, MembershipPlan
from app.memberships.utils import generate_unique_membership_code
from app.notifications.service import has_recent_notification, notify_member
from app.common.enums import MembershipStatus, NotificationType


def create_plan(
    db: Session, *, actor_id: uuid.UUID, gym_id: uuid.UUID, name: str, duration_days: int, price
) -> MembershipPlan:
    plan = MembershipPlan(gym_id=gym_id, name=name, duration_days=duration_days, price=price)
    db.add(plan)
    db.flush()

    log_audit_event(
        db, actor_user_id=actor_id, gym_id=gym_id, action="MEMBERSHIP_PLAN_CREATED",
        entity_type="membership_plan", entity_id=str(plan.id), metadata={"name": name},
    )
    db.commit()
    db.refresh(plan)
    return plan


def list_plans(db: Session, *, gym_id: uuid.UUID, params: PageParams) -> PaginatedData:
    stmt = select(MembershipPlan).where(MembershipPlan.gym_id == gym_id).order_by(MembershipPlan.created_at.desc())
    return paginate(db, stmt, params)


def create_membership(
    db: Session, *, actor_id: uuid.UUID, gym_id: uuid.UUID, member_id: uuid.UUID, plan_id: uuid.UUID,
    start_date: date | None,
) -> Membership:
    # Scoped lookups: a member_id/plan_id from another gym simply won't be
    # found, so this can never create a membership that crosses tenants.
    member = db.scalar(select(Member).where(Member.id == member_id, Member.gym_id == gym_id))
    if member is None:
        raise NotFoundError("Member not found.", code="MEMBER_NOT_FOUND")

    plan = db.scalar(select(MembershipPlan).where(MembershipPlan.id == plan_id, MembershipPlan.gym_id == gym_id))
    if plan is None:
        raise NotFoundError("Membership plan not found.", code="PLAN_NOT_FOUND")

    gym = db.get(Gym, gym_id)

    resolved_start = start_date or date.today()
    resolved_end = resolved_start + timedelta(days=plan.duration_days)
    code = generate_unique_membership_code(db, gym_slug=gym.slug)

    membership = Membership(
        gym_id=gym_id,
        member_id=member.id,
        plan_id=plan.id,
        membership_id_code=code,
        is_linked=False,
        status=MembershipStatus.ACTIVE,
        start_date=resolved_start,
        end_date=resolved_end,
    )
    db.add(membership)
    db.flush()

    log_audit_event(
        db, actor_user_id=actor_id, gym_id=gym_id, action="MEMBERSHIP_CREATED",
        entity_type="membership", entity_id=str(membership.id),
        metadata={"member_id": str(member.id), "membership_id_code": code},
    )
    db.commit()
    db.refresh(membership)
    return membership


def get_membership(db: Session, *, gym_id: uuid.UUID, membership_id: uuid.UUID) -> Membership:
    membership = db.scalar(select(Membership).where(Membership.id == membership_id, Membership.gym_id == gym_id))
    if membership is None:
        raise NotFoundError("Membership not found.", code="MEMBERSHIP_NOT_FOUND")
    return membership


def list_member_memberships(db: Session, *, gym_id: uuid.UUID, member_id: uuid.UUID) -> list[Membership]:
    """Used by the member-facing 'my membership' view (section 14) and by
    owner member-detail pages (section 13)."""
    stmt = (
        select(Membership)
        .where(Membership.gym_id == gym_id, Membership.member_id == member_id)
        .order_by(Membership.created_at.desc())
    )
    return list(db.scalars(stmt))


def get_current_membership(db: Session, *, gym_id: uuid.UUID, member_id: uuid.UUID) -> Membership | None:
    """The member's most recently created membership — used to decide
    whether they're currently RESTRICTED (section 10, consumed by the
    workouts/progress modules)."""
    stmt = (
        select(Membership)
        .where(Membership.gym_id == gym_id, Membership.member_id == member_id)
        .order_by(Membership.created_at.desc())
        .limit(1)
    )
    return db.scalar(stmt)


def assert_not_restricted(db: Session, *, gym_id: uuid.UUID, member_id: uuid.UUID) -> None:
    """
    Section 10: a RESTRICTED member must not be able to create new workout
    sessions, exercise logs, or progress records. Also blocks EXPIRED and
    CANCELLED — both of which are equally-or-more terminal (a member reaches
    EXPIRED only by staying RESTRICTED for 30+ days, so un-blocking them at
    that point would be a regression, not a relaxation). Enforced here, in
    the backend, and called from every write endpoint in workouts/progress —
    never left to the mobile client to hide a button.
    """
    membership = get_current_membership(db, gym_id=gym_id, member_id=member_id)
    if membership is not None and blocks_new_tracking(membership):
        raise MembershipRestrictedError()


def run_membership_checks(db: Session, *, gym_id: uuid.UUID | None = None) -> dict:
    """
    Applies the payment-due/restricted/expiry state machine to every
    non-terminal membership (optionally scoped to one gym). This is the
    exact function Celery Beat's check_membership_payment_status /
    check_membership_expiry tasks call (section 12/14) — implemented here,
    independent of Celery, so it's directly unit/integration-testable and
    reusable, and so repeated runs are provably idempotent (section 36).
    """
    today = date.today()
    grace_days = settings.MEMBERSHIP_GRACE_PERIOD_DAYS

    stmt = select(Membership).where(
        Membership.status.in_(
            [MembershipStatus.ACTIVE, MembershipStatus.PAYMENT_DUE, MembershipStatus.RESTRICTED]
        )
    )
    if gym_id is not None:
        stmt = stmt.where(Membership.gym_id == gym_id)

    memberships = list(db.scalars(stmt))
    marked_payment_due = 0
    marked_restricted = 0
    marked_expired = 0
    notifications_sent = 0

    for membership in memberships:
        before_status = membership.status
        payment_result = apply_payment_due_check(membership, today=today, grace_period_days=grace_days)
        expiry_result = apply_expiry_check(membership, today=today)

        if payment_result.changed or expiry_result.changed:
            log_audit_event(
                db, actor_user_id=None, gym_id=membership.gym_id, action="MEMBERSHIP_STATUS_CHANGED",
                entity_type="membership", entity_id=str(membership.id),
                metadata={"from": before_status.value, "to": membership.status.value, "source": "scheduled_check"},
            )
            if membership.status == MembershipStatus.PAYMENT_DUE and payment_result.changed:
                marked_payment_due += 1
                if _notify_transition(db, membership, NotificationType.PAYMENT_OVERDUE,
                                       "Payment overdue", "Your membership payment is overdue. Please renew to avoid restriction."):
                    notifications_sent += 1
            elif membership.status == MembershipStatus.RESTRICTED and payment_result.changed:
                marked_restricted += 1
                if _notify_transition(db, membership, NotificationType.MEMBERSHIP_RESTRICTED,
                                       "Membership restricted", "Your membership has been restricted due to overdue payment."):
                    notifications_sent += 1
            elif membership.status == MembershipStatus.EXPIRED and expiry_result.changed:
                marked_expired += 1

    # Separate pass: proactive "nearing expiry" notice for still-ACTIVE
    # memberships, deduplicated so repeated runs don't spam the same member.
    expiring_soon_cutoff = today + timedelta(days=3)
    expiring_stmt = select(Membership).where(
        Membership.status == MembershipStatus.ACTIVE, Membership.end_date <= expiring_soon_cutoff,
        Membership.end_date >= today,
    )
    if gym_id is not None:
        expiring_stmt = expiring_stmt.where(Membership.gym_id == gym_id)

    for membership in db.scalars(expiring_stmt):
        if has_recent_notification(
            db, member_id=membership.member_id, type=NotificationType.MEMBERSHIP_EXPIRING, since=membership.start_date
        ):
            continue
        member = db.get(Member, membership.member_id)
        sent = notify_member(
            db, gym_id=membership.gym_id, member=member, type=NotificationType.MEMBERSHIP_EXPIRING,
            title="Membership expiring soon",
            message=f"Your membership expires on {membership.end_date.isoformat()}.",
        )
        if sent:
            notifications_sent += 1

    db.commit()
    return {
        "checked": len(memberships),
        "marked_payment_due": marked_payment_due,
        "marked_restricted": marked_restricted,
        "marked_expired": marked_expired,
        "notifications_sent": notifications_sent,
    }


def _notify_transition(db: Session, membership: Membership, notif_type: NotificationType, title: str, message: str) -> bool:
    member = db.get(Member, membership.member_id)
    sent = notify_member(db, gym_id=membership.gym_id, member=member, type=notif_type, title=title, message=message)
    return sent is not None
