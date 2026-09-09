"""
Membership status state machine (section 9):

    ACTIVE --(end_date passes)--> PAYMENT_DUE --(grace period exceeded)--> RESTRICTED
    PAYMENT_DUE --(payment recorded)--> ACTIVE
    RESTRICTED --(payment recorded)--> ACTIVE
    RESTRICTED --(long unpaid)--> EXPIRED   (owner action or long-running Beat task)
    * --(owner cancels)--> CANCELLED

Grace-period boundary rule (section 35, explicitly required to be unambiguous):
elapsed_days = (today - payment_due_since).days.
  elapsed_days <= grace_period_days  -> stays PAYMENT_DUE
  elapsed_days >  grace_period_days  -> RESTRICTED
So a membership overdue by exactly 7 days is still PAYMENT_DUE; day 8 tips it
into RESTRICTED. This module only mutates in-memory objects — the caller
(service layer) owns the transaction / commit, which is what makes these
functions trivially unit-testable and safely reusable from a Celery task.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

from app.common.enums import MembershipStatus
from app.memberships.models import Membership

# How many days after RESTRICTED (on top of the grace period already elapsed)
# before a membership is considered permanently EXPIRED rather than still
# recoverable by paying. Not in the original spec's explicit numbers, so
# documented here as a deliberate, single, testable choice.
EXPIRE_AFTER_RESTRICTED_DAYS = 30


@dataclass
class TransitionResult:
    changed: bool
    from_status: MembershipStatus
    to_status: MembershipStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


def apply_payment_due_check(membership: Membership, *, today: date, grace_period_days: int) -> TransitionResult:
    """
    Run for a single membership. Handles both possible transitions in one
    idempotent pass:
      1. ACTIVE whose end_date has passed -> PAYMENT_DUE
      2. PAYMENT_DUE whose grace period has elapsed -> RESTRICTED
    Calling this repeatedly on an already-transitioned membership is a no-op
    (changed=False) — this is what makes repeated Celery Beat runs safe
    (section 12: "must be idempotent").
    """
    original_status = membership.status

    if membership.status == MembershipStatus.ACTIVE and today > membership.end_date:
        membership.status = MembershipStatus.PAYMENT_DUE
        # Stored as a tz-aware datetime (column type) but semantically "the
        # day it became due" — midnight UTC on end_date.
        membership.payment_due_since = datetime.combine(membership.end_date, datetime.min.time(), tzinfo=timezone.utc)
        return TransitionResult(True, original_status, membership.status)

    if membership.status == MembershipStatus.PAYMENT_DUE and membership.payment_due_since is not None:
        elapsed_days = (today - membership.payment_due_since.date()).days
        if elapsed_days > grace_period_days:
            membership.status = MembershipStatus.RESTRICTED
            membership.restricted_at = _now()
            return TransitionResult(True, original_status, membership.status)

    return TransitionResult(False, original_status, original_status)


def apply_expiry_check(membership: Membership, *, today: date) -> TransitionResult:
    """RESTRICTED for too long -> EXPIRED (a separate, longer-horizon check;
    section 12 lists check_membership_expiry as its own scheduled task)."""
    original_status = membership.status
    if membership.status == MembershipStatus.RESTRICTED and membership.restricted_at is not None:
        days_restricted = (today - membership.restricted_at.date()).days
        if days_restricted > EXPIRE_AFTER_RESTRICTED_DAYS:
            membership.status = MembershipStatus.EXPIRED
            return TransitionResult(True, original_status, membership.status)
    return TransitionResult(False, original_status, original_status)


def reactivate_with_payment(membership: Membership, *, plan_duration_days: int, payment_date: date) -> TransitionResult:
    """
    A payment has just been recorded for this membership. Restores ACTIVE
    from either PAYMENT_DUE or RESTRICTED and renews end_date from the
    payment date. Does NOT touch progress/workout history — those live on
    separate tables and are never modified here (section 9: "Never delete
    previous member progress").
    """
    original_status = membership.status
    membership.status = MembershipStatus.ACTIVE
    membership.payment_due_since = None
    membership.restricted_at = None
    membership.end_date = payment_date + timedelta(days=plan_duration_days)
    return TransitionResult(original_status != MembershipStatus.ACTIVE, original_status, membership.status)


def is_restricted(membership: Membership) -> bool:
    """True only for RESTRICTED specifically — used where the caller cares
    about that exact status (e.g. dashboard counts, notification triggers)."""
    return membership.status == MembershipStatus.RESTRICTED


def blocks_new_tracking(membership: Membership) -> bool:
    """
    Section 10 names RESTRICTED explicitly, but EXPIRED and CANCELLED are
    equally-or-more terminal states a member can reach FROM RESTRICTED (see
    EXPIRE_AFTER_RESTRICTED_DAYS above) — a member who was correctly blocked
    while RESTRICTED must not become UN-blocked by aging further into
    EXPIRED. This is the function that should gate all new
    session/log/progress creation; `is_restricted` alone is intentionally
    narrower and used only where the exact RESTRICTED status matters.
    """
    return membership.status in (MembershipStatus.RESTRICTED, MembershipStatus.EXPIRED, MembershipStatus.CANCELLED)
