"""
Celery application instance + Celery Beat schedule.

Task modules live under app/tasks/*.py and are autodiscovered below.
Beat schedule implements section 12 of the spec: membership + analytics
housekeeping jobs that must run on a fixed cadence and be authoritative
(the mobile/owner clients never compute membership state themselves).
"""
from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

# Must be imported before any task touches the ORM, so every model's
# relationship() string references (e.g. Gym.users -> "User") can resolve
# regardless of which task module happens to run first. Without this, a
# worker process that only imports app.tasks.membership_tasks (which never
# happens to import app.users.models directly) fails the FIRST query with
# "failed to locate a name" from SQLAlchemy's mapper configuration.
import app.models_registry  # noqa: E402,F401

celery_app = Celery(
    "gym_saas",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

celery_app.autodiscover_tasks(
    [
        "app.tasks.membership_tasks",
        "app.tasks.analytics_tasks",
        "app.tasks.ai_tasks",
        "app.tasks.notification_tasks",
    ]
)

# Section 12: minimum required scheduled tasks.
celery_app.conf.beat_schedule = {
    "check-membership-payment-status": {
        "task": "tasks.membership.check_membership_payment_status",
        "schedule": crontab(minute="*/15"),
    },
    "check-membership-expiry": {
        "task": "tasks.membership.check_membership_expiry",
        "schedule": crontab(hour=2, minute=0),
    },
    "check-inactive-members": {
        "task": "tasks.membership.check_inactive_members",
        "schedule": crontab(hour=3, minute=0),
    },
    "generate-periodic-analytics": {
        "task": "tasks.analytics.generate_periodic_analytics",
        "schedule": crontab(hour=4, minute=0),
    },
    "generate-ai-insights": {
        "task": "tasks.ai.generate_insights_for_active_members",
        "schedule": crontab(hour=5, minute=0),
    },
}
