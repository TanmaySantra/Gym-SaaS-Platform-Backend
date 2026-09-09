"""Analytics scheduled task (section 12)."""
from __future__ import annotations

import logging

from app.analytics import service as analytics_service
from app.common.audit import log_audit_event
from app.core.celery import celery_app
from app.core.database import task_session
from app.gyms.models import Gym

logger = logging.getLogger("gym_saas.tasks.analytics")


@celery_app.task(name="tasks.analytics.generate_periodic_analytics", bind=True, max_retries=3)
def generate_periodic_analytics(self):
    """Computes a basic per-gym snapshot and records it via audit_logs
    (see app/analytics/service.py docstring for why there's no dedicated
    analytics table in this prototype)."""
    try:
        with task_session() as db:
            from sqlalchemy import select

            gym_ids = list(db.scalars(select(Gym.id)))
            for gym_id in gym_ids:
                snapshot = analytics_service.compute_gym_snapshot(db, gym_id=gym_id)
                log_audit_event(
                    db, actor_user_id=None, gym_id=gym_id, action="ANALYTICS_SNAPSHOT",
                    entity_type="gym", entity_id=str(gym_id), metadata=snapshot,
                )
            db.commit()
            result = {"gyms_processed": len(gym_ids)}
            logger.info("generate_periodic_analytics: %s", result)
            return result
    except Exception as exc:  # noqa: BLE001
        logger.exception("generate_periodic_analytics failed")
        raise self.retry(exc=exc, countdown=60) from exc
