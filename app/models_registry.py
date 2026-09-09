"""
Import every ORM model module here so `Base.metadata` is fully populated
before Alembic autogenerate or `Base.metadata.create_all()` runs.

Nothing else should need to import this directly except alembic/env.py and
test fixtures that spin up a schema.
"""
from app.core.database import Base  # noqa: F401

from app.gyms.models import Gym  # noqa: F401
from app.users.models import User  # noqa: F401
from app.members.models import Member  # noqa: F401
from app.memberships.models import MembershipPlan, Membership  # noqa: F401
from app.workouts.models import (  # noqa: F401
    Exercise,
    WorkoutPlan,
    WorkoutPlanExercise,
    WorkoutSession,
    ExerciseLog,
)
from app.progress.models import ProgressRecord  # noqa: F401
from app.attendance.models import Attendance  # noqa: F401
from app.payments.models import Payment, Expense  # noqa: F401
from app.ai.models import AIInsight  # noqa: F401
from app.notifications.models import Notification  # noqa: F401
from app.auth.models import LoginSession  # noqa: F401
from app.common.models import AuditLog  # noqa: F401

__all__ = [
    "Base",
    "Gym",
    "User",
    "Member",
    "MembershipPlan",
    "Membership",
    "Exercise",
    "WorkoutPlan",
    "WorkoutPlanExercise",
    "WorkoutSession",
    "ExerciseLog",
    "ProgressRecord",
    "Attendance",
    "Payment",
    "Expense",
    "AIInsight",
    "Notification",
    "LoginSession",
    "AuditLog",
]
