"""
Integration tests for the real Celery tasks (sections 12/36).

Uses Celery's `.apply()` which executes the task function synchronously in
the current process against the real (test) database — no broker or worker
needed for the test suite itself. The live end-to-end broker/worker pipeline
was separately verified manually against real Redis + Postgres.
"""
from datetime import date, timedelta

from app.common.enums import GymStatus, MembershipStatus, UserRole
from app.core.security import hash_password
from app.gyms.models import Gym
from app.members.models import Member
from app.memberships.models import Membership, MembershipPlan
from app.users.models import User


class _FixedSessionContext:
    """A context manager that yields a fixed session instead of opening a new
    one — lets tests observe exactly what the task wrote via the same
    session/transaction the test fixture already controls."""

    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *exc_info):
        return False


def setup_gym_with_member(db_session, slug):
    gym = Gym(name="Celery Test", slug=slug, status=GymStatus.ACTIVE)
    db_session.add(gym)
    db_session.flush()
    owner = User(
        email=f"owner-{slug}@test.com", full_name="Owner", hashed_password=hash_password("OwnerPass123!"),
        role=UserRole.OWNER, gym_id=gym.id,
    )
    member = Member(gym_id=gym.id, full_name="Member")
    plan = MembershipPlan(gym_id=gym.id, name="Monthly", duration_days=30, price=50)
    db_session.add_all([owner, member, plan])
    db_session.commit()
    db_session.refresh(gym)
    db_session.refresh(member)
    db_session.refresh(plan)
    return gym, member, plan


def make_membership(db_session, gym_id, member_id, plan_id, code, status, end_date, payment_due_since=None):
    m = Membership(
        gym_id=gym_id, member_id=member_id, plan_id=plan_id, membership_id_code=code,
        status=status, start_date=end_date - timedelta(days=30), end_date=end_date,
        payment_due_since=payment_due_since,
    )
    db_session.add(m)
    db_session.commit()
    db_session.refresh(m)
    return m


class TestMembershipPaymentStatusTask:
    def test_task_transitions_overdue_membership(self, db_session, monkeypatch):
        from app.tasks import membership_tasks

        gym, member, plan = setup_gym_with_member(db_session, "task-overdue")
        membership = make_membership(
            db_session, gym.id, member.id, plan.id, "TASK1-00001", MembershipStatus.ACTIVE,
            date.today() - timedelta(days=1),
        )

        # Patch task_session to yield the SAME test session/transaction the
        # fixture uses, so the task's writes are visible to our assertions.
        monkeypatch.setattr(membership_tasks, "task_session", lambda: _FixedSessionContext(db_session))

        result = membership_tasks.check_membership_payment_status.apply().get()
        assert result["marked_payment_due"] == 1

        db_session.refresh(membership)
        assert membership.status == MembershipStatus.PAYMENT_DUE

    def test_task_is_idempotent_across_two_runs(self, db_session, monkeypatch):
        from app.tasks import membership_tasks

        gym, member, plan = setup_gym_with_member(db_session, "task-idempotent")
        make_membership(
            db_session, gym.id, member.id, plan.id, "TASK2-00001", MembershipStatus.ACTIVE,
            date.today() - timedelta(days=1),
        )
        monkeypatch.setattr(membership_tasks, "task_session", lambda: _FixedSessionContext(db_session))

        result1 = membership_tasks.check_membership_payment_status.apply().get()
        result2 = membership_tasks.check_membership_payment_status.apply().get()
        assert result1["marked_payment_due"] == 1
        assert result2["marked_payment_due"] == 0


class TestInactiveMembersTask:
    def test_flags_member_with_no_recent_activity(self, db_session, monkeypatch):
        from app.tasks import membership_tasks

        gym, member, plan = setup_gym_with_member(db_session, "task-inactive")
        monkeypatch.setattr(membership_tasks, "task_session", lambda: _FixedSessionContext(db_session))

        result = membership_tasks.check_inactive_members.apply().get()
        assert result["flagged_inactive"] == 1

        from app.common.models import AuditLog

        flagged = db_session.query(AuditLog).filter(AuditLog.action == "MEMBER_FLAGGED_INACTIVE").all()
        assert any(str(member.id) == a.entity_id for a in flagged)

    def test_does_not_flag_recently_active_member(self, db_session, monkeypatch):
        from app.tasks import membership_tasks
        from app.attendance.models import Attendance

        gym, member, plan = setup_gym_with_member(db_session, "task-active-recent")
        db_session.add(Attendance(gym_id=gym.id, member_id=member.id, date=date.today()))
        db_session.commit()

        monkeypatch.setattr(membership_tasks, "task_session", lambda: _FixedSessionContext(db_session))
        result = membership_tasks.check_inactive_members.apply().get()
        assert result["flagged_inactive"] == 0


class TestAnalyticsTask:
    def test_generates_snapshot_for_each_gym(self, db_session, monkeypatch):
        from app.tasks import analytics_tasks

        setup_gym_with_member(db_session, "task-analytics-a")
        setup_gym_with_member(db_session, "task-analytics-b")

        monkeypatch.setattr(analytics_tasks, "task_session", lambda: _FixedSessionContext(db_session))
        result = analytics_tasks.generate_periodic_analytics.apply().get()
        assert result["gyms_processed"] >= 2

        from app.common.models import AuditLog

        snapshots = db_session.query(AuditLog).filter(AuditLog.action == "ANALYTICS_SNAPSHOT").all()
        assert len(snapshots) >= 2
