"""
Membership scheduled tasks (section 12).

Both tasks run against ALL gyms (gym_id=None passed to the service layer) —
this is correct and safe specifically BECAUSE run_membership_checks itself
still scopes every query by gym_id internally when iterating; there is no
cross-tenant leakage, this is just "do the housekeeping pass for the whole
platform" the way a real scheduled job would.
"""
from __future__ import annotations

import logging

from app.core.celery import celery_app
from app.core.database import task_session
from app.memberships import service as membership_service

logger = logging.getLogger("gym_saas.tasks.membership")


@celery_app.task(name="tasks.membership.check_membership_payment_status", bind=True, max_retries=3)
def check_membership_payment_status(self):
    """
    Runs apply_payment_due_check across every non-terminal membership:
    ACTIVE past end_date -> PAYMENT_DUE; PAYMENT_DUE past the grace period ->
    RESTRICTED. Idempotent (section 36) — safe to run as often as scheduled
    even if a prior run partially applied.
    """
    try:
        with task_session() as db:
            result = membership_service.run_membership_checks(db, gym_id=None)
            logger.info("check_membership_payment_status: %s", result)
            return result
    except Exception as exc:  # noqa: BLE001 - Celery retry needs the broad catch
        logger.exception("check_membership_payment_status failed")
        raise self.retry(exc=exc, countdown=60) from exc


@celery_app.task(name="tasks.membership.check_membership_expiry", bind=True, max_retries=3)
def check_membership_expiry(self):
    """
    Separate scheduled entry per section 12's explicit task list. Calls the
    same underlying idempotent routine (which already includes the
    RESTRICTED -> EXPIRED expiry check) — documented here as a deliberate
    choice rather than duplicating the query logic in two places.
    """
    try:
        with task_session() as db:
            result = membership_service.run_membership_checks(db, gym_id=None)
            logger.info("check_membership_expiry: %s", result)
            return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("check_membership_expiry failed")
        raise self.retry(exc=exc, countdown=60) from exc


@celery_app.task(name="tasks.membership.check_inactive_members", bind=True, max_retries=3)
def check_inactive_members(self, inactive_days: int = 30):
    """
    Flags members with no workout session AND no attendance record in the
    last `inactive_days` days. V1 records this via audit_logs (no dedicated
    notification type exists yet for this — see Phase 19) rather than
    silently doing nothing, so the signal is at least inspectable.
    """
    from datetime import datetime, timedelta, timezone

    from sqlalchemy import select

    from app.attendance.models import Attendance
    from app.common.audit import log_audit_event
    from app.members.models import Member
    from app.workouts.models import WorkoutSession

    try:
        with task_session() as db:
            cutoff = datetime.now(timezone.utc) - timedelta(days=inactive_days)
            cutoff_date = cutoff.date()

            recently_active_member_ids = set(
                db.scalars(select(WorkoutSession.member_id).where(WorkoutSession.started_at >= cutoff))
            ) | set(
                db.scalars(select(Attendance.member_id).where(Attendance.date >= cutoff_date))
            )

            member_rows = db.execute(select(Member.id, Member.gym_id)).all()
            inactive_count = 0
            for member_id, gym_id in member_rows:
                if member_id not in recently_active_member_ids:
                    inactive_count += 1
                    log_audit_event(
                        db, actor_user_id=None, gym_id=gym_id, action="MEMBER_FLAGGED_INACTIVE",
                        entity_type="member", entity_id=str(member_id),
                        metadata={"inactive_days_threshold": inactive_days},
                    )
            db.commit()
            result = {"checked": len(member_rows), "flagged_inactive": inactive_count}
            logger.info("check_inactive_members: %s", result)
            return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("check_inactive_members failed")
        raise self.retry(exc=exc, countdown=60) from exc
