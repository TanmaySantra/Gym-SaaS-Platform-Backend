"""
Performance sanity check (section 41).

NOT a pytest suite with hard pass/fail timing thresholds (those are flaky
across environments) - this is a diagnostic script that seeds realistic
volume, times the operations the spec calls out, and reports obvious N+1
behavior. Run manually:

    DATABASE_URL=... python -m scripts.performance_check
"""
from __future__ import annotations

import time
import uuid
from datetime import date, timedelta

from sqlalchemy import event

import app.models_registry  # noqa: F401
from app.core.database import SessionLocal, engine
from app.common.enums import GymStatus, MembershipStatus, UserRole, WorkoutSessionStatus
from app.core.security import hash_password
from app.gyms.models import Gym
from app.members.models import Member
from app.memberships.models import Membership, MembershipPlan
from app.progress.models import ProgressRecord
from app.users.models import User
from app.workouts.models import Exercise, ExerciseLog, WorkoutSession


def timed(label):
    class _Ctx:
        def __enter__(self):
            self.start = time.perf_counter()
            return self
        def __exit__(self, *a):
            elapsed = time.perf_counter() - self.start
            print(f"  {label}: {elapsed*1000:.1f} ms")
    return _Ctx()


def seed_volume_data(db, n_members=100, progress_per_member=12, logs_per_member=12):
    """~100 members, 1000+ progress records, 1000+ exercise logs."""
    gym = Gym(name="Perf Test Gym", slug=f"perf-{uuid.uuid4().hex[:8]}", status=GymStatus.ACTIVE)
    db.add(gym)
    db.flush()

    owner = User(
        email=f"perf-owner-{uuid.uuid4().hex[:8]}@test.com", full_name="Perf Owner",
        hashed_password=hash_password("PerfPass123!"), role=UserRole.OWNER, gym_id=gym.id,
    )
    plan = MembershipPlan(gym_id=gym.id, name="Monthly", duration_days=30, price=50)
    exercise = Exercise(gym_id=gym.id, name="Squat")
    db.add_all([owner, plan, exercise])
    db.flush()

    members = [Member(gym_id=gym.id, full_name=f"Perf Member {i}") for i in range(n_members)]
    db.add_all(members)
    db.flush()

    memberships = [
        Membership(
            gym_id=gym.id, member_id=m.id, plan_id=plan.id, membership_id_code=f"PERF{i:04d}-{uuid.uuid4().hex[:5].upper()}",
            status=MembershipStatus.ACTIVE, start_date=date.today() - timedelta(days=5), end_date=date.today() + timedelta(days=25),
        )
        for i, m in enumerate(members)
    ]
    db.add_all(memberships)

    progress_rows = []
    for m in members:
        for j in range(progress_per_member):
            progress_rows.append(ProgressRecord(
                gym_id=gym.id, member_id=m.id, weight_kg=80 - j * 0.2,
                recorded_at=date.today() - timedelta(days=j * 2),
            ))
    db.bulk_save_objects(progress_rows)

    sessions = []
    for m in members:
        s = WorkoutSession(gym_id=gym.id, member_id=m.id, status=WorkoutSessionStatus.COMPLETED)
        sessions.append(s)
    db.add_all(sessions)
    db.flush()

    logs = []
    for s in sessions:
        for j in range(logs_per_member):
            logs.append(ExerciseLog(
                workout_session_id=s.id, exercise_id=exercise.id, set_number=(j % 5) + 1, reps=10, weight_kg=50,
            ))
    db.bulk_save_objects(logs)

    db.commit()
    print(f"Seeded: {n_members} members, {len(progress_rows)} progress records, {len(logs)} exercise logs")
    return gym.id


def count_queries(db, fn):
    count = {"n": 0}
    def _before_cursor_execute(*args, **kwargs):
        count["n"] += 1
    event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    try:
        result = fn()
    finally:
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)
    return result, count["n"]


def main():
    db = SessionLocal()
    print("=== Seeding volume data (section 41: 100 members, 1000+ logs/records) ===")
    with timed("seed"):
        gym_id = seed_volume_data(db)

    from app.common.pagination import PageParams
    from app.analytics import service as analytics_service
    from app.memberships import service as membership_service
    from app.members import service as members_service
    from app.payments import service as payments_service

    print("\n=== Query timing (section 41) ===")
    with timed("dashboard summary (aggregate counts across 100 members)"):
        analytics_service.get_owner_dashboard_summary(db, gym_id=gym_id)

    page_params = PageParams(page=1, page_size=20)
    (result, n_queries) = count_queries(db, lambda: analytics_service.get_dashboard_member_rows(db, gym_id=gym_id, params=page_params))
    print(f"  dashboard member list (page_size=20 of 100 total): {n_queries} SQL queries for this page")
    if n_queries > 100:
        print("  ^^^ WARNING: query count is not bounded by page size - looks like an N+1 issue")
    else:
        print("  -> bounded by page size, not total member count (pagination is doing its job)")

    with timed("members list (paginated, page_size=20)"):
        members_service.list_members(db, gym_id=gym_id, params=page_params)

    with timed("finance summary"):
        payments_service.get_finance_summary(db, gym_id=gym_id)

    with timed("run_membership_checks across 100 memberships"):
        result = membership_service.run_membership_checks(db, gym_id=gym_id)
        print(f"    -> {result}")

    with timed("run_membership_checks AGAIN (idempotency at volume)"):
        result2 = membership_service.run_membership_checks(db, gym_id=gym_id)
        print(f"    -> {result2}")

    db.close()

    print("\n=== Done ===")


if __name__ == "__main__":
    main()
