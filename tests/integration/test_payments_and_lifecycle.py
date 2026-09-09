"""Integration tests for /api/v1/payments and run_membership_checks (sections
18/35/36/38), against real Postgres data."""
from datetime import date, timedelta

from app.common.enums import GymStatus, MembershipStatus, UserRole
from app.core.security import hash_password
from app.gyms.models import Gym
from app.members.models import Member
from app.memberships import service as membership_service
from app.memberships.models import Membership, MembershipPlan
from app.users.models import User


def login(client, email, password):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def setup_gym_owner_member_plan(db_session, slug="payflow"):
    gym = Gym(name="Pay Flow Gym", slug=slug, status=GymStatus.ACTIVE)
    db_session.add(gym)
    db_session.flush()
    owner = User(
        email=f"owner-{slug}@test.com", full_name="Owner", hashed_password=hash_password("OwnerPass123!"),
        role=UserRole.OWNER, gym_id=gym.id,
    )
    member = Member(gym_id=gym.id, full_name="Test Member")
    plan = MembershipPlan(gym_id=gym.id, name="Monthly", duration_days=30, price=50)
    db_session.add_all([owner, member, plan])
    db_session.commit()
    db_session.refresh(gym)
    db_session.refresh(owner)
    db_session.refresh(member)
    db_session.refresh(plan)
    return gym, owner, member, plan


def make_membership(db_session, gym_id, member_id, plan_id, code, status, end_date, payment_due_since=None, restricted_at=None):
    m = Membership(
        gym_id=gym_id, member_id=member_id, plan_id=plan_id, membership_id_code=code,
        status=status, start_date=end_date - timedelta(days=30), end_date=end_date,
        payment_due_since=payment_due_since, restricted_at=restricted_at,
    )
    db_session.add(m)
    db_session.commit()
    db_session.refresh(m)
    return m


class TestRecordPayment:
    def test_record_payment_on_active_membership_renews_end_date(self, client, db_session):
        gym, owner, member, plan = setup_gym_owner_member_plan(db_session, "active-pay")
        membership = make_membership(
            db_session, gym.id, member.id, plan.id, "ACTPAY-00001", MembershipStatus.ACTIVE, date(2026, 6, 30)
        )
        token = login(client, owner.email, "OwnerPass123!")
        resp = client.post(
            "/api/v1/payments",
            json={"membership_id": str(membership.id), "amount": "50.00", "payment_date": "2026-06-25"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["status"] == "PAID"

        db_session.refresh(membership)
        assert membership.status == MembershipStatus.ACTIVE
        assert membership.end_date == date(2026, 7, 25)

    def test_record_payment_reactivates_payment_due_membership(self, client, db_session):
        gym, owner, member, plan = setup_gym_owner_member_plan(db_session, "due-pay")
        membership = make_membership(
            db_session, gym.id, member.id, plan.id, "DUEPAY-00001", MembershipStatus.PAYMENT_DUE,
            date(2026, 6, 1), payment_due_since=None,
        )
        token = login(client, owner.email, "OwnerPass123!")
        resp = client.post(
            "/api/v1/payments",
            json={"membership_id": str(membership.id), "amount": "50.00", "payment_date": "2026-06-05"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        db_session.refresh(membership)
        assert membership.status == MembershipStatus.ACTIVE
        assert membership.payment_due_since is None

    def test_record_payment_reactivates_restricted_membership(self, client, db_session):
        gym, owner, member, plan = setup_gym_owner_member_plan(db_session, "restricted-pay")
        membership = make_membership(
            db_session, gym.id, member.id, plan.id, "RESPAY-00001", MembershipStatus.RESTRICTED, date(2026, 6, 1)
        )
        token = login(client, owner.email, "OwnerPass123!")
        resp = client.post(
            "/api/v1/payments",
            json={"membership_id": str(membership.id), "amount": "50.00", "payment_date": "2026-06-20"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201
        db_session.refresh(membership)
        assert membership.status == MembershipStatus.ACTIVE
        assert membership.restricted_at is None

    def test_cannot_pay_cancelled_membership(self, client, db_session):
        gym, owner, member, plan = setup_gym_owner_member_plan(db_session, "cancelled-pay")
        membership = make_membership(
            db_session, gym.id, member.id, plan.id, "CANPAY-00001", MembershipStatus.CANCELLED, date(2026, 6, 1)
        )
        token = login(client, owner.email, "OwnerPass123!")
        resp = client.post(
            "/api/v1/payments",
            json={"membership_id": str(membership.id), "amount": "50.00"},
            headers=auth_header(token),
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "MEMBERSHIP_TERMINAL_STATE"

    def test_negative_amount_rejected(self, client, db_session):
        gym, owner, member, plan = setup_gym_owner_member_plan(db_session, "neg-pay")
        membership = make_membership(
            db_session, gym.id, member.id, plan.id, "NEGPAY-00001", MembershipStatus.ACTIVE, date(2026, 12, 1)
        )
        token = login(client, owner.email, "OwnerPass123!")
        resp = client.post(
            "/api/v1/payments",
            json={"membership_id": str(membership.id), "amount": "-10"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    def test_cross_tenant_payment_rejected(self, client, db_session):
        gym_a, owner_a, member_a, plan_a = setup_gym_owner_member_plan(db_session, "tenant-a-pay")
        gym_b, owner_b, member_b, plan_b = setup_gym_owner_member_plan(db_session, "tenant-b-pay")
        membership_b = make_membership(
            db_session, gym_b.id, member_b.id, plan_b.id, "TENB-00001", MembershipStatus.ACTIVE, date(2026, 12, 1)
        )
        token_a = login(client, owner_a.email, "OwnerPass123!")
        resp = client.post(
            "/api/v1/payments",
            json={"membership_id": str(membership_b.id), "amount": "50.00"},
            headers=auth_header(token_a),
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "MEMBERSHIP_NOT_FOUND"


class TestRunMembershipChecks:
    """Exercises app.memberships.service.run_membership_checks directly —
    this is exactly what Celery Beat will call in Phase 13-14, tested here
    independent of Celery (sections 12/35/36)."""

    def test_active_past_end_date_becomes_payment_due(self, db_session):
        gym, owner, member, plan = setup_gym_owner_member_plan(db_session, "check-1")
        membership = make_membership(
            db_session, gym.id, member.id, plan.id, "CHK1-00001", MembershipStatus.ACTIVE,
            date.today() - timedelta(days=1),
        )
        result = membership_service.run_membership_checks(db_session, gym_id=gym.id)
        db_session.refresh(membership)
        assert membership.status == MembershipStatus.PAYMENT_DUE
        assert result["marked_payment_due"] == 1

    def test_payment_due_beyond_grace_becomes_restricted(self, db_session):
        gym, owner, member, plan = setup_gym_owner_member_plan(db_session, "check-2")
        due_since_dt = None
        from datetime import datetime, timezone
        due_date = date.today() - timedelta(days=8)
        membership = make_membership(
            db_session, gym.id, member.id, plan.id, "CHK2-00001", MembershipStatus.PAYMENT_DUE,
            due_date, payment_due_since=datetime.combine(due_date, datetime.min.time(), tzinfo=timezone.utc),
        )
        result = membership_service.run_membership_checks(db_session, gym_id=gym.id)
        db_session.refresh(membership)
        assert membership.status == MembershipStatus.RESTRICTED
        assert result["marked_restricted"] == 1

    def test_running_check_twice_is_idempotent(self, db_session):
        gym, owner, member, plan = setup_gym_owner_member_plan(db_session, "check-3")
        make_membership(
            db_session, gym.id, member.id, plan.id, "CHK3-00001", MembershipStatus.ACTIVE,
            date.today() - timedelta(days=1),
        )
        result1 = membership_service.run_membership_checks(db_session, gym_id=gym.id)
        result2 = membership_service.run_membership_checks(db_session, gym_id=gym.id)
        assert result1["marked_payment_due"] == 1
        assert result2["marked_payment_due"] == 0  # already transitioned, no double-processing

    def test_check_does_not_cross_tenant_boundaries(self, db_session):
        gym_a, owner_a, member_a, plan_a = setup_gym_owner_member_plan(db_session, "check-a")
        gym_b, owner_b, member_b, plan_b = setup_gym_owner_member_plan(db_session, "check-b")
        make_membership(
            db_session, gym_a.id, member_a.id, plan_a.id, "CHKA-00001", MembershipStatus.ACTIVE,
            date.today() - timedelta(days=1),
        )
        membership_b = make_membership(
            db_session, gym_b.id, member_b.id, plan_b.id, "CHKB-00001", MembershipStatus.ACTIVE,
            date.today() - timedelta(days=1),
        )
        # Only check gym A.
        result = membership_service.run_membership_checks(db_session, gym_id=gym_a.id)
        assert result["checked"] == 1
        db_session.refresh(membership_b)
        assert membership_b.status == MembershipStatus.ACTIVE  # untouched

    def test_active_within_end_date_is_not_touched(self, db_session):
        gym, owner, member, plan = setup_gym_owner_member_plan(db_session, "check-4")
        membership = make_membership(
            db_session, gym.id, member.id, plan.id, "CHK4-00001", MembershipStatus.ACTIVE,
            date.today() + timedelta(days=10),
        )
        result = membership_service.run_membership_checks(db_session, gym_id=gym.id)
        db_session.refresh(membership)
        assert membership.status == MembershipStatus.ACTIVE
        assert result["marked_payment_due"] == 0
        assert result["marked_restricted"] == 0

    def test_progress_history_untouched_by_restriction(self, db_session):
        """Section 9: restriction must never delete or touch historical
        progress records."""
        from app.progress.models import ProgressRecord

        gym, owner, member, plan = setup_gym_owner_member_plan(db_session, "check-5")
        record = ProgressRecord(gym_id=gym.id, member_id=member.id, weight_kg=80)
        db_session.add(record)
        db_session.commit()
        record_id = record.id

        due_date = date.today() - timedelta(days=8)
        from datetime import datetime, timezone
        make_membership(
            db_session, gym.id, member.id, plan.id, "CHK5-00001", MembershipStatus.PAYMENT_DUE,
            due_date, payment_due_since=datetime.combine(due_date, datetime.min.time(), tzinfo=timezone.utc),
        )
        membership_service.run_membership_checks(db_session, gym_id=gym.id)

        still_there = db_session.get(ProgressRecord, record_id)
        assert still_there is not None
        assert still_there.weight_kg == 80
