"""Integration tests for /api/v1/members and /api/v1/memberships (sections 33/34/38)."""
import uuid
from datetime import date

from app.common.enums import GymStatus, MembershipStatus, UserRole
from app.core.security import hash_password
from app.gyms.models import Gym
from app.members.models import Member
from app.memberships.models import Membership, MembershipPlan
from app.users.models import User


def login(client, email, password):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def make_gym(db_session, slug):
    gym = Gym(name=f"Gym {slug}", slug=slug, status=GymStatus.ACTIVE)
    db_session.add(gym)
    db_session.commit()
    db_session.refresh(gym)
    return gym


def make_owner(db_session, gym_id, email, password="OwnerPass123!"):
    user = User(
        email=email, full_name="Owner", hashed_password=hash_password(password), role=UserRole.OWNER, gym_id=gym_id
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


def make_member(db_session, gym_id, full_name="Test Member"):
    member = Member(gym_id=gym_id, full_name=full_name)
    db_session.add(member)
    db_session.commit()
    db_session.refresh(member)
    return member


def make_plan(db_session, gym_id, name="Monthly", duration_days=30, price=50):
    plan = MembershipPlan(gym_id=gym_id, name=name, duration_days=duration_days, price=price)
    db_session.add(plan)
    db_session.commit()
    db_session.refresh(plan)
    return plan


def make_membership(db_session, gym_id, member_id, plan_id, code):
    m = Membership(
        gym_id=gym_id, member_id=member_id, plan_id=plan_id, membership_id_code=code,
        status=MembershipStatus.ACTIVE, start_date=date.today(), end_date=date.today(),
    )
    db_session.add(m)
    db_session.commit()
    db_session.refresh(m)
    return m


class TwoTenantFixture:
    """Sets up Gym A / Owner A / Member A and Gym B / Owner B / Member B —
    the canonical cross-tenant test setup (section 33)."""

    def __init__(self, client, db_session):
        self.gym_a = make_gym(db_session, "gym-a-members")
        self.gym_b = make_gym(db_session, "gym-b-members")
        make_owner(db_session, self.gym_a.id, "ownera@test.com")
        make_owner(db_session, self.gym_b.id, "ownerb@test.com")
        self.member_a = make_member(db_session, self.gym_a.id, "Member A")
        self.member_b = make_member(db_session, self.gym_b.id, "Member B")
        self.plan_a = make_plan(db_session, self.gym_a.id, "Plan A")
        self.plan_b = make_plan(db_session, self.gym_b.id, "Plan B")
        self.token_a = login(client, "ownera@test.com", "OwnerPass123!")
        self.token_b = login(client, "ownerb@test.com", "OwnerPass123!")


class TestMemberCreation:
    def test_owner_creates_member(self, client, db_session):
        gym = make_gym(db_session, "solo-gym")
        make_owner(db_session, gym.id, "owner1@test.com")
        token = login(client, "owner1@test.com", "OwnerPass123!")
        resp = client.post("/api/v1/members", json={"full_name": "Jane Doe", "phone": "+1234567890"}, headers=auth_header(token))
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["full_name"] == "Jane Doe"
        assert data["is_linked"] is False

    def test_member_role_cannot_create_member(self, client, db_session):
        gym = make_gym(db_session, "member-role-gym")
        member = make_member(db_session, gym.id)
        user = User(
            email="member1@test.com", full_name=member.full_name, hashed_password=hash_password("MemberPass123!"),
            role=UserRole.MEMBER, gym_id=gym.id,
        )
        db_session.add(user)
        db_session.commit()
        db_session.refresh(user)
        member.user_id = user.id
        db_session.commit()

        token = login(client, "member1@test.com", "MemberPass123!")
        resp = client.post("/api/v1/members", json={"full_name": "New Guy"}, headers=auth_header(token))
        assert resp.status_code == 403

    def test_missing_full_name_returns_422(self, client, db_session):
        gym = make_gym(db_session, "validation-gym")
        make_owner(db_session, gym.id, "owner1@test.com")
        token = login(client, "owner1@test.com", "OwnerPass123!")
        resp = client.post("/api/v1/members", json={}, headers=auth_header(token))
        assert resp.status_code == 422


class TestCrossTenantMemberIDOR:
    """Section 33/34: attempt to access another gym's member via direct ID."""

    def test_owner_a_sees_only_own_members_in_list(self, client, db_session):
        fx = TwoTenantFixture(client, db_session)
        resp_a = client.get("/api/v1/members", headers=auth_header(fx.token_a))
        names = [m["full_name"] for m in resp_a.json()["data"]["items"]]
        assert "Member A" in names
        assert "Member B" not in names

    def test_owner_a_cannot_fetch_member_b_by_id(self, client, db_session):
        fx = TwoTenantFixture(client, db_session)
        resp = client.get(f"/api/v1/members/{fx.member_b.id}", headers=auth_header(fx.token_a))
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "MEMBER_NOT_FOUND"

    def test_owner_b_cannot_fetch_member_a_by_id(self, client, db_session):
        fx = TwoTenantFixture(client, db_session)
        resp = client.get(f"/api/v1/members/{fx.member_a.id}", headers=auth_header(fx.token_b))
        assert resp.status_code == 404

    def test_owner_a_can_fetch_own_member(self, client, db_session):
        fx = TwoTenantFixture(client, db_session)
        resp = client.get(f"/api/v1/members/{fx.member_a.id}", headers=auth_header(fx.token_a))
        assert resp.status_code == 200
        assert resp.json()["data"]["full_name"] == "Member A"

    def test_random_nonexistent_id_also_404s_identically(self, client, db_session):
        """A truly nonexistent id and a cross-tenant id must be indistinguishable
        to the caller — same status, same error code."""
        fx = TwoTenantFixture(client, db_session)
        resp_random = client.get(f"/api/v1/members/{uuid.uuid4()}", headers=auth_header(fx.token_a))
        resp_cross_tenant = client.get(f"/api/v1/members/{fx.member_b.id}", headers=auth_header(fx.token_a))
        assert resp_random.status_code == resp_cross_tenant.status_code == 404
        assert resp_random.json()["error"]["code"] == resp_cross_tenant.json()["error"]["code"]


class TestMembershipPlans:
    def test_owner_creates_plan(self, client, db_session):
        gym = make_gym(db_session, "plan-gym")
        make_owner(db_session, gym.id, "owner1@test.com")
        token = login(client, "owner1@test.com", "OwnerPass123!")
        resp = client.post(
            "/api/v1/memberships/plans", json={"name": "Annual", "duration_days": 365, "price": "499.99"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["data"]["duration_days"] == 365

    def test_negative_price_rejected(self, client, db_session):
        gym = make_gym(db_session, "neg-price-gym")
        make_owner(db_session, gym.id, "owner1@test.com")
        token = login(client, "owner1@test.com", "OwnerPass123!")
        resp = client.post(
            "/api/v1/memberships/plans", json={"name": "Bad", "duration_days": 30, "price": "-10"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    def test_zero_duration_rejected(self, client, db_session):
        gym = make_gym(db_session, "zero-dur-gym")
        make_owner(db_session, gym.id, "owner1@test.com")
        token = login(client, "owner1@test.com", "OwnerPass123!")
        resp = client.post(
            "/api/v1/memberships/plans", json={"name": "Bad", "duration_days": 0, "price": "10"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422


class TestMembershipCreationAndCrossTenantIDOR:
    def test_owner_creates_membership_generates_code(self, client, db_session):
        fx = TwoTenantFixture(client, db_session)
        resp = client.post(
            "/api/v1/memberships",
            json={"member_id": str(fx.member_a.id), "plan_id": str(fx.plan_a.id)},
            headers=auth_header(fx.token_a),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert "-" in data["membership_id_code"]
        assert data["status"] == "ACTIVE"
        assert data["is_linked"] is False

    def test_end_date_computed_from_plan_duration(self, client, db_session):
        fx = TwoTenantFixture(client, db_session)
        resp = client.post(
            "/api/v1/memberships",
            json={"member_id": str(fx.member_a.id), "plan_id": str(fx.plan_a.id), "start_date": "2026-01-01"},
            headers=auth_header(fx.token_a),
        )
        data = resp.json()["data"]
        assert data["start_date"] == "2026-01-01"
        assert data["end_date"] == "2026-01-31"  # +30 days

    def test_owner_a_cannot_create_membership_for_member_b(self, client, db_session):
        """Cross-tenant write attempt: Owner A tries to create a membership
        pointing at Member B's id (IDOR via request body, section 33)."""
        fx = TwoTenantFixture(client, db_session)
        resp = client.post(
            "/api/v1/memberships",
            json={"member_id": str(fx.member_b.id), "plan_id": str(fx.plan_a.id)},
            headers=auth_header(fx.token_a),
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "MEMBER_NOT_FOUND"

    def test_owner_a_cannot_use_gym_b_plan(self, client, db_session):
        """Cross-tenant write attempt via plan_id instead of member_id."""
        fx = TwoTenantFixture(client, db_session)
        resp = client.post(
            "/api/v1/memberships",
            json={"member_id": str(fx.member_a.id), "plan_id": str(fx.plan_b.id)},
            headers=auth_header(fx.token_a),
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "PLAN_NOT_FOUND"

    def test_owner_a_cannot_fetch_gym_b_membership(self, client, db_session):
        fx = TwoTenantFixture(client, db_session)
        membership_b = make_membership(db_session, fx.gym_b.id, fx.member_b.id, fx.plan_b.id, "GYMB01-XXXXX")
        resp = client.get(f"/api/v1/memberships/{membership_b.id}", headers=auth_header(fx.token_a))
        assert resp.status_code == 404

    def test_two_memberships_get_different_codes(self, client, db_session):
        fx = TwoTenantFixture(client, db_session)
        member2 = make_member(db_session, fx.gym_a.id, "Member A2")
        resp1 = client.post(
            "/api/v1/memberships", json={"member_id": str(fx.member_a.id), "plan_id": str(fx.plan_a.id)},
            headers=auth_header(fx.token_a),
        )
        resp2 = client.post(
            "/api/v1/memberships", json={"member_id": str(member2.id), "plan_id": str(fx.plan_a.id)},
            headers=auth_header(fx.token_a),
        )
        assert resp1.json()["data"]["membership_id_code"] != resp2.json()["data"]["membership_id_code"]


class TestMembershipLinking:
    def test_full_link_flow(self, client, db_session):
        fx = TwoTenantFixture(client, db_session)
        create_resp = client.post(
            "/api/v1/memberships", json={"member_id": str(fx.member_a.id), "plan_id": str(fx.plan_a.id)},
            headers=auth_header(fx.token_a),
        )
        code = create_resp.json()["data"]["membership_id_code"]

        link_resp = client.post(
            "/api/v1/members/link",
            json={"membership_id_code": code, "email": "membera@test.com", "password": "MemberPass123!"},
        )
        assert link_resp.status_code == 200, link_resp.text
        assert link_resp.json()["data"]["email"] == "membera@test.com"

        # The newly linked member can now log in as MEMBER, scoped to gym A.
        member_token = login(client, "membera@test.com", "MemberPass123!")
        me = client.get("/api/v1/auth/me", headers=auth_header(member_token)).json()["data"]
        assert me["role"] == "MEMBER"
        assert me["gym_id"] == str(fx.gym_a.id)

    def test_invalid_code_rejected(self, client):
        resp = client.post(
            "/api/v1/members/link",
            json={"membership_id_code": "NOPE-00000", "email": "x@test.com", "password": "Password123!"},
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "INVALID_MEMBERSHIP_ID"

    def test_cannot_link_same_code_twice(self, client, db_session):
        fx = TwoTenantFixture(client, db_session)
        create_resp = client.post(
            "/api/v1/memberships", json={"member_id": str(fx.member_a.id), "plan_id": str(fx.plan_a.id)},
            headers=auth_header(fx.token_a),
        )
        code = create_resp.json()["data"]["membership_id_code"]

        first = client.post(
            "/api/v1/members/link",
            json={"membership_id_code": code, "email": "first@test.com", "password": "Password123!"},
        )
        assert first.status_code == 200

        second = client.post(
            "/api/v1/members/link",
            json={"membership_id_code": code, "email": "second@test.com", "password": "Password123!"},
        )
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "ALREADY_LINKED"

    def test_cannot_link_with_already_used_email(self, client, db_session):
        fx = TwoTenantFixture(client, db_session)
        member2 = make_member(db_session, fx.gym_a.id, "Member A2")
        create_resp = client.post(
            "/api/v1/memberships", json={"member_id": str(member2.id), "plan_id": str(fx.plan_a.id)},
            headers=auth_header(fx.token_a),
        )
        code = create_resp.json()["data"]["membership_id_code"]

        resp = client.post(
            "/api/v1/members/link",
            json={"membership_id_code": code, "email": "ownera@test.com", "password": "Password123!"},
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "EMAIL_TAKEN"

    def test_membership_id_cannot_be_used_as_login_password(self, client, db_session):
        """Section 8: the membership ID must not double as a password."""
        fx = TwoTenantFixture(client, db_session)
        create_resp = client.post(
            "/api/v1/memberships", json={"member_id": str(fx.member_a.id), "plan_id": str(fx.plan_a.id)},
            headers=auth_header(fx.token_a),
        )
        code = create_resp.json()["data"]["membership_id_code"]
        client.post(
            "/api/v1/members/link",
            json={"membership_id_code": code, "email": "membera@test.com", "password": "RealPassword1!"},
        )
        # Trying to log in using the membership code as the password must fail.
        resp = client.post("/api/v1/auth/login", json={"email": "membera@test.com", "password": code})
        assert resp.status_code == 401
