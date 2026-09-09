"""Integration tests for /api/v1/payments/expenses and finance summary (section 18)."""
from datetime import date

from app.common.enums import GymStatus, MembershipStatus, UserRole
from app.core.security import hash_password
from app.gyms.models import Gym
from app.members.models import Member
from app.memberships.models import Membership, MembershipPlan
from app.payments.models import Payment
from app.common.enums import PaymentStatus
from app.users.models import User


def login(client, email, password):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def setup_gym(db_session, slug):
    gym = Gym(name="Finance Gym", slug=slug, status=GymStatus.ACTIVE)
    db_session.add(gym)
    db_session.flush()
    owner = User(
        email=f"owner-{slug}@test.com", full_name="Owner", hashed_password=hash_password("OwnerPass123!"),
        role=UserRole.OWNER, gym_id=gym.id,
    )
    db_session.add(owner)
    db_session.commit()
    db_session.refresh(gym)
    db_session.refresh(owner)
    return gym, owner


class TestExpenses:
    def test_owner_records_expense(self, client, db_session):
        gym, owner = setup_gym(db_session, "expense-basic")
        token = login(client, owner.email, "OwnerPass123!")
        resp = client.post(
            "/api/v1/payments/expenses", json={"category": "Equipment", "amount": "250.00"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["data"]["category"] == "Equipment"

    def test_negative_expense_rejected(self, client, db_session):
        gym, owner = setup_gym(db_session, "expense-neg")
        token = login(client, owner.email, "OwnerPass123!")
        resp = client.post(
            "/api/v1/payments/expenses", json={"category": "Rent", "amount": "-500"}, headers=auth_header(token)
        )
        assert resp.status_code == 422

    def test_member_cannot_record_expense(self, client, db_session):
        gym, owner = setup_gym(db_session, "expense-member-block")
        member = Member(gym_id=gym.id, full_name="M")
        db_session.add(member)
        db_session.flush()
        member_user = User(
            email="member-expense@test.com", full_name="M", hashed_password=hash_password("MemberPass123!"),
            role=UserRole.MEMBER, gym_id=gym.id,
        )
        db_session.add(member_user)
        db_session.commit()

        token = login(client, "member-expense@test.com", "MemberPass123!")
        resp = client.post(
            "/api/v1/payments/expenses", json={"category": "Snacks", "amount": "10"}, headers=auth_header(token)
        )
        assert resp.status_code == 403


class TestFinanceSummary:
    def test_summary_computes_revenue_expenses_profit(self, client, db_session):
        gym, owner = setup_gym(db_session, "finance-calc")
        member = Member(gym_id=gym.id, full_name="M")
        plan = MembershipPlan(gym_id=gym.id, name="Monthly", duration_days=30, price=50)
        db_session.add_all([member, plan])
        db_session.flush()
        membership = Membership(
            gym_id=gym.id, member_id=member.id, plan_id=plan.id, membership_id_code="FIN-00001",
            status=MembershipStatus.ACTIVE, start_date=date(2026, 1, 1), end_date=date(2026, 2, 1),
        )
        db_session.add(membership)
        db_session.flush()

        db_session.add_all([
            Payment(gym_id=gym.id, member_id=member.id, membership_id=membership.id, amount=100,
                    payment_date=date(2026, 1, 1), status=PaymentStatus.PAID),
            Payment(gym_id=gym.id, member_id=member.id, membership_id=membership.id, amount=50,
                    payment_date=date(2026, 1, 15), status=PaymentStatus.PAID),
        ])
        db_session.commit()

        token = login(client, owner.email, "OwnerPass123!")
        client.post("/api/v1/payments/expenses", json={"category": "Rent", "amount": "60"}, headers=auth_header(token))

        resp = client.get("/api/v1/payments/finance/summary", headers=auth_header(token))
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert float(data["total_revenue"]) == 150.0
        assert float(data["total_expenses"]) == 60.0
        assert float(data["net_profit"]) == 90.0

    def test_outstanding_count_reflects_payment_due_and_restricted(self, client, db_session):
        gym, owner = setup_gym(db_session, "finance-outstanding")
        plan = MembershipPlan(gym_id=gym.id, name="Monthly", duration_days=30, price=50)
        db_session.add(plan)
        db_session.flush()

        for i, status in enumerate([MembershipStatus.ACTIVE, MembershipStatus.PAYMENT_DUE, MembershipStatus.RESTRICTED]):
            member = Member(gym_id=gym.id, full_name=f"M{i}")
            db_session.add(member)
            db_session.flush()
            db_session.add(Membership(
                gym_id=gym.id, member_id=member.id, plan_id=plan.id, membership_id_code=f"OUT-{i:05d}",
                status=status, start_date=date(2026, 1, 1), end_date=date(2026, 2, 1),
            ))
        db_session.commit()

        token = login(client, owner.email, "OwnerPass123!")
        resp = client.get("/api/v1/payments/finance/summary", headers=auth_header(token))
        assert resp.json()["data"]["outstanding_payments_count"] == 2

    def test_finance_summary_scoped_per_gym(self, client, db_session):
        gym_a, owner_a = setup_gym(db_session, "finance-a")
        gym_b, owner_b = setup_gym(db_session, "finance-b")
        member_b = Member(gym_id=gym_b.id, full_name="MB")
        plan_b = MembershipPlan(gym_id=gym_b.id, name="Monthly", duration_days=30, price=999)
        db_session.add_all([member_b, plan_b])
        db_session.flush()
        membership_b = Membership(
            gym_id=gym_b.id, member_id=member_b.id, plan_id=plan_b.id, membership_id_code="FINB-00001",
            status=MembershipStatus.ACTIVE, start_date=date(2026, 1, 1), end_date=date(2026, 2, 1),
        )
        db_session.add(membership_b)
        db_session.flush()
        db_session.add(Payment(
            gym_id=gym_b.id, member_id=member_b.id, membership_id=membership_b.id, amount=999,
            payment_date=date(2026, 1, 1), status=PaymentStatus.PAID,
        ))
        db_session.commit()

        token_a = login(client, owner_a.email, "OwnerPass123!")
        resp = client.get("/api/v1/payments/finance/summary", headers=auth_header(token_a))
        assert float(resp.json()["data"]["total_revenue"]) == 0.0  # Gym A never sees Gym B's revenue
