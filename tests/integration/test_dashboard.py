"""Integration tests for /api/v1/analytics/dashboard* (section 13)."""
from datetime import date, timedelta

from app.common.enums import GymStatus, MembershipStatus, UserRole, WorkoutSessionStatus
from app.core.security import hash_password
from app.gyms.models import Gym
from app.members.models import Member
from app.memberships.models import Membership, MembershipPlan
from app.payments.models import Payment, Expense
from app.common.enums import PaymentStatus
from app.progress.models import ProgressRecord
from app.attendance.models import Attendance
from app.users.models import User


def login(client, email, password):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def setup_gym(db_session, slug):
    gym = Gym(name="Dashboard Gym", slug=slug, status=GymStatus.ACTIVE)
    db_session.add(gym)
    db_session.flush()
    owner = User(
        email=f"owner-{slug}@test.com", full_name="Owner", hashed_password=hash_password("OwnerPass123!"),
        role=UserRole.OWNER, gym_id=gym.id,
    )
    plan = MembershipPlan(gym_id=gym.id, name="Monthly", duration_days=30, price=50)
    db_session.add_all([owner, plan])
    db_session.commit()
    db_session.refresh(gym)
    db_session.refresh(owner)
    db_session.refresh(plan)
    return gym, owner, plan


def add_member_with_membership(db_session, gym, plan, name, status, end_date, code):
    member = Member(gym_id=gym.id, full_name=name)
    db_session.add(member)
    db_session.flush()
    membership = Membership(
        gym_id=gym.id, member_id=member.id, plan_id=plan.id, membership_id_code=code,
        status=status, start_date=end_date - timedelta(days=20), end_date=end_date,
    )
    db_session.add(membership)
    db_session.commit()
    db_session.refresh(member)
    db_session.refresh(membership)
    return member, membership


class TestDashboardSummary:
    def test_summary_reflects_seeded_data_across_every_dimension(self, client, db_session):
        gym, owner, plan = setup_gym(db_session, "dash-full")

        m_active, mem_active = add_member_with_membership(
            db_session, gym, plan, "Active One", MembershipStatus.ACTIVE, date.today() + timedelta(days=20), "DASH-A"
        )
        m_due, mem_due = add_member_with_membership(
            db_session, gym, plan, "Due One", MembershipStatus.PAYMENT_DUE, date.today() - timedelta(days=3), "DASH-B"
        )
        m_restricted, mem_restricted = add_member_with_membership(
            db_session, gym, plan, "Restricted One", MembershipStatus.RESTRICTED, date.today() - timedelta(days=10), "DASH-C"
        )
        m_expiring, mem_expiring = add_member_with_membership(
            db_session, gym, plan, "Expiring Soon", MembershipStatus.ACTIVE, date.today() + timedelta(days=3), "DASH-D"
        )

        db_session.add(Payment(
            gym_id=gym.id, member_id=m_active.id, membership_id=mem_active.id, amount=50,
            payment_date=date.today(), status=PaymentStatus.PAID,
        ))
        db_session.add(Expense(gym_id=gym.id, category="Rent", amount=20, date=date.today()))
        db_session.add(Attendance(gym_id=gym.id, member_id=m_active.id, date=date.today()))
        db_session.commit()

        token = login(client, owner.email, "OwnerPass123!")
        resp = client.get("/api/v1/analytics/dashboard", headers=auth_header(token))
        assert resp.status_code == 200, resp.text
        data = resp.json()["data"]

        assert data["total_members"] == 4
        assert data["active_members"] == 2  # active + expiring-soon are both ACTIVE
        assert data["payment_due_members"] == 1
        assert data["restricted_members"] == 1
        assert data["expiring_within_7_days"] == 1  # only the one expiring in 3 days
        assert data["attendance_today_count"] == 1
        assert float(data["total_revenue"]) == 50.0
        assert float(data["total_expenses"]) == 20.0
        assert float(data["net_profit"]) == 30.0

    def test_dashboard_scoped_per_gym(self, client, db_session):
        gym_a, owner_a, plan_a = setup_gym(db_session, "dash-scope-a")
        gym_b, owner_b, plan_b = setup_gym(db_session, "dash-scope-b")
        add_member_with_membership(
            db_session, gym_b, plan_b, "B Member", MembershipStatus.ACTIVE, date.today() + timedelta(days=10), "DASHB-1"
        )

        token_a = login(client, owner_a.email, "OwnerPass123!")
        resp = client.get("/api/v1/analytics/dashboard", headers=auth_header(token_a))
        assert resp.json()["data"]["total_members"] == 0  # Gym A never sees Gym B's member

    def test_member_cannot_access_dashboard(self, client, db_session):
        gym, owner, plan = setup_gym(db_session, "dash-member-block")
        member = Member(gym_id=gym.id, full_name="M")
        db_session.add(member)
        db_session.flush()
        member_user = User(
            email="dashmember@test.com", full_name="M", hashed_password=hash_password("MemberPass123!"),
            role=UserRole.MEMBER, gym_id=gym.id,
        )
        db_session.add(member_user)
        db_session.commit()

        token = login(client, "dashmember@test.com", "MemberPass123!")
        resp = client.get("/api/v1/analytics/dashboard", headers=auth_header(token))
        assert resp.status_code == 403


class TestDashboardMemberList:
    def test_member_row_shows_status_attendance_and_trend(self, client, db_session):
        gym, owner, plan = setup_gym(db_session, "dash-rows")
        member, membership = add_member_with_membership(
            db_session, gym, plan, "Trend Member", MembershipStatus.ACTIVE, date.today() + timedelta(days=15), "ROWS-1"
        )
        db_session.add_all([
            ProgressRecord(gym_id=gym.id, member_id=member.id, weight_kg=80,
                            recorded_at=date.today() - timedelta(days=20)),
            ProgressRecord(gym_id=gym.id, member_id=member.id, weight_kg=76,
                            recorded_at=date.today() - timedelta(days=1)),
        ])
        db_session.add(Attendance(gym_id=gym.id, member_id=member.id, date=date.today()))
        db_session.commit()

        token = login(client, owner.email, "OwnerPass123!")
        resp = client.get("/api/v1/analytics/dashboard/members", headers=auth_header(token))
        assert resp.status_code == 200
        rows = resp.json()["data"]["items"]
        assert len(rows) == 1
        row = rows[0]
        assert row["full_name"] == "Trend Member"
        assert row["membership_id_code"] == "ROWS-1"
        assert row["membership_status"] == "ACTIVE"
        assert row["progress_trend"] == "down"  # 80 -> 76 kg

    def test_member_with_no_data_shows_no_data_trend(self, client, db_session):
        gym, owner, plan = setup_gym(db_session, "dash-rows-empty")
        add_member_with_membership(
            db_session, gym, plan, "Blank Member", MembershipStatus.ACTIVE, date.today() + timedelta(days=15), "ROWS-2"
        )
        token = login(client, owner.email, "OwnerPass123!")
        resp = client.get("/api/v1/analytics/dashboard/members", headers=auth_header(token))
        row = resp.json()["data"]["items"][0]
        assert row["progress_trend"] == "no data"
        assert row["attendance_percentage_last_30_days"] == 0.0

    def test_member_list_scoped_per_gym(self, client, db_session):
        gym_a, owner_a, plan_a = setup_gym(db_session, "dash-list-a")
        gym_b, owner_b, plan_b = setup_gym(db_session, "dash-list-b")
        add_member_with_membership(
            db_session, gym_b, plan_b, "B Member", MembershipStatus.ACTIVE, date.today() + timedelta(days=10), "LISTB-1"
        )
        token_a = login(client, owner_a.email, "OwnerPass123!")
        resp = client.get("/api/v1/analytics/dashboard/members", headers=auth_header(token_a))
        assert resp.json()["data"]["total"] == 0
