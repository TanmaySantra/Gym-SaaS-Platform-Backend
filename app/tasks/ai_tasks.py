"""AI insight generation scheduled task (sections 12/19/20)."""
from __future__ import annotations

import logging

from app.core.celery import celery_app
from app.core.database import task_session

logger = logging.getLogger("gym_saas.tasks.ai")


@celery_app.task(name="tasks.ai.generate_insights_for_active_members", bind=True, max_retries=2)
def generate_insights_for_active_members(self):
    """
    Runs the AI pipeline for every member with a currently ACTIVE
    membership, across all gyms. Section 20's core safety property: one
    member's AI failure (timeout, malformed response, provider error) is
    caught and logged per-member and never aborts the batch.
    """
    from sqlalchemy import select

    from app.ai import service as ai_service
    from app.ai.client import AIProviderError
    from app.common.enums import MembershipStatus
    from app.memberships.models import Membership

    try:
        with task_session() as db:
            rows = list(
                db.execute(
                    select(Membership.gym_id, Membership.member_id).where(
                        Membership.status == MembershipStatus.ACTIVE
                    )
                ).all()
            )
            succeeded, failed = 0, 0
            for gym_id, member_id in rows:
                try:
                    ai_service.generate_insight_for_member(db, gym_id=gym_id, member_id=member_id)
                    succeeded += 1
                except (AIProviderError, ai_service.AIResponseValidationError) as exc:
                    logger.warning("AI insight failed for member %s: %s", member_id, exc.message)
                    failed += 1
                except Exception:
                    logger.exception("Unexpected error generating AI insight for member %s", member_id)
                    failed += 1

            result = {"processed": len(rows), "succeeded": succeeded, "failed": failed}
            logger.info("generate_insights_for_active_members: %s", result)
            return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("generate_insights_for_active_members failed")
        raise self.retry(exc=exc, countdown=120) from exc
