"""Integration tests for /api/v1/auth/* (sections 32/38)."""
from app.core.security import hash_password
from app.common.enums import UserRole
from app.users.models import User


def make_owner(db_session, gym_id, email="owner@test.com", password="OwnerPass123!"):
    user = User(
        email=email,
        full_name="Test Owner",
        hashed_password=hash_password(password),
        role=UserRole.OWNER,
        gym_id=gym_id,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


class TestLogin:
    def test_login_success_returns_tokens(self, client, super_admin):
        resp = client.post(
            "/api/v1/auth/login", json={"email": "admin@test.com", "password": "AdminPass123!"}
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["success"] is True
        assert "access_token" in body["data"]
        assert "refresh_token" in body["data"]

    def test_login_wrong_password(self, client, super_admin):
        resp = client.post("/api/v1/auth/login", json={"email": "admin@test.com", "password": "wrong"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"

    def test_login_nonexistent_user(self, client):
        resp = client.post("/api/v1/auth/login", json={"email": "nobody@test.com", "password": "whatever"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "INVALID_CREDENTIALS"

    def test_login_inactive_account(self, client, db_session, super_admin):
        super_admin.is_active = False
        db_session.commit()
        resp = client.post(
            "/api/v1/auth/login", json={"email": "admin@test.com", "password": "AdminPass123!"}
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "ACCOUNT_INACTIVE"

    def test_login_missing_fields_returns_422(self, client):
        resp = client.post("/api/v1/auth/login", json={"email": "admin@test.com"})
        assert resp.status_code == 422


class TestSignup:
    def test_member_signup_links_membership_and_returns_tokens(self, client, db_session):
        from app.gyms.models import Gym
        from app.common.enums import GymStatus, MembershipStatus
        from app.members.models import Member
        from app.memberships.models import Membership, MembershipPlan

        gym = Gym(name="Signup Gym", slug="signup-gym", status=GymStatus.ACTIVE)
        db_session.add(gym)
        db_session.flush()
        member = Member(gym_id=gym.id, full_name="New Member")
        plan = MembershipPlan(gym_id=gym.id, name="Monthly", duration_days=30, price=50)
        db_session.add_all([member, plan])
        db_session.flush()
        membership = Membership(
            gym_id=gym.id,
            member_id=member.id,
            plan_id=plan.id,
            membership_id_code="SIGNUP-001",
            status=MembershipStatus.ACTIVE,
        )
        db_session.add(membership)
        db_session.commit()

        resp = client.post(
            "/api/v1/auth/signup",
            json={
                "membership_id_code": "SIGNUP-001",
                "email": "new-member@test.com",
                "password": "MemberPass123!",
            },
        )

        assert resp.status_code == 201
        data = resp.json()["data"]
        assert data["user"]["role"] == "MEMBER"
        assert data["user"]["gym_id"] == str(gym.id)
        assert data["tokens"]["access_token"]
        assert data["tokens"]["refresh_token"]

        me = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {data['tokens']['access_token']}"},
        )
        assert me.status_code == 200

    def test_signup_rejects_invalid_membership_code(self, client):
        resp = client.post(
            "/api/v1/auth/signup",
            json={
                "membership_id_code": "DOES-NOT-EXIST",
                "email": "new-member@test.com",
                "password": "MemberPass123!",
            },
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "INVALID_MEMBERSHIP_ID"

    def test_login_invalid_email_format_returns_422(self, client):
        resp = client.post("/api/v1/auth/login", json={"email": "not-an-email", "password": "x"})
        assert resp.status_code == 422


class TestMe:
    def test_me_requires_token(self, client):
        resp = client.get("/api/v1/auth/me")
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "MISSING_TOKEN"

    def test_me_rejects_garbage_token(self, client):
        resp = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer garbage"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "INVALID_TOKEN"

    def test_me_rejects_refresh_token_used_as_access(self, client, super_admin):
        login_resp = client.post(
            "/api/v1/auth/login", json={"email": "admin@test.com", "password": "AdminPass123!"}
        )
        refresh_token = login_resp.json()["data"]["refresh_token"]
        resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {refresh_token}"})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "INVALID_TOKEN"

    def test_me_returns_correct_identity(self, client, super_admin):
        login_resp = client.post(
            "/api/v1/auth/login", json={"email": "admin@test.com", "password": "AdminPass123!"}
        )
        access_token = login_resp.json()["data"]["access_token"]
        resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["email"] == "admin@test.com"
        assert data["role"] == "SUPER_ADMIN"
        assert data["gym_id"] is None


class TestRefresh:
    def test_refresh_issues_new_access_token(self, client, super_admin):
        login_resp = client.post(
            "/api/v1/auth/login", json={"email": "admin@test.com", "password": "AdminPass123!"}
        )
        refresh_token = login_resp.json()["data"]["refresh_token"]
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert resp.status_code == 200
        new_access = resp.json()["data"]["access_token"]

        me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {new_access}"})
        assert me_resp.status_code == 200

    def test_refresh_rejects_access_token(self, client, super_admin):
        login_resp = client.post(
            "/api/v1/auth/login", json={"email": "admin@test.com", "password": "AdminPass123!"}
        )
        access_token = login_resp.json()["data"]["access_token"]
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": access_token})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"

    def test_refresh_rejects_garbage(self, client):
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": "garbage"})
        assert resp.status_code == 401


class TestLogout:
    def test_logout_revokes_session_for_access_token(self, client, super_admin):
        login_resp = client.post(
            "/api/v1/auth/login", json={"email": "admin@test.com", "password": "AdminPass123!"}
        )
        access_token = login_resp.json()["data"]["access_token"]

        logout_resp = client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {access_token}"})
        assert logout_resp.status_code == 200

        # The SAME access token must now be rejected — this is the critical
        # behavior: logout is server-side revocation, not client amnesia.
        me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
        assert me_resp.status_code == 401
        assert me_resp.json()["error"]["code"] == "SESSION_REVOKED"

    def test_logout_revokes_refresh_token_too(self, client, super_admin):
        login_resp = client.post(
            "/api/v1/auth/login", json={"email": "admin@test.com", "password": "AdminPass123!"}
        )
        access_token = login_resp.json()["data"]["access_token"]
        refresh_token = login_resp.json()["data"]["refresh_token"]

        client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {access_token}"})

        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_token})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "SESSION_REVOKED"

    def test_logout_without_token_is_rejected(self, client):
        resp = client.post("/api/v1/auth/logout")
        assert resp.status_code == 401

    def test_two_sessions_independent_logout(self, client, super_admin):
        """Logging out of one session (e.g. one device) must not affect another."""
        login1 = client.post(
            "/api/v1/auth/login", json={"email": "admin@test.com", "password": "AdminPass123!"}
        ).json()["data"]
        login2 = client.post(
            "/api/v1/auth/login", json={"email": "admin@test.com", "password": "AdminPass123!"}
        ).json()["data"]

        client.post("/api/v1/auth/logout", headers={"Authorization": f"Bearer {login1['access_token']}"})

        # Session 1 is dead.
        resp1 = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {login1['access_token']}"})
        assert resp1.status_code == 401

        # Session 2 is untouched.
        resp2 = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {login2['access_token']}"})
        assert resp2.status_code == 200


class TestRoleSeparation:
    def test_owner_login_returns_owner_role_and_gym_id(self, client, db_session):
        from app.gyms.models import Gym
        from app.common.enums import GymStatus

        gym = Gym(name="Test Gym", slug="test-gym", status=GymStatus.ACTIVE)
        db_session.add(gym)
        db_session.commit()
        db_session.refresh(gym)

        make_owner(db_session, gym.id)

        login_resp = client.post(
            "/api/v1/auth/login", json={"email": "owner@test.com", "password": "OwnerPass123!"}
        )
        access_token = login_resp.json()["data"]["access_token"]
        me_resp = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {access_token}"})
        data = me_resp.json()["data"]
        assert data["role"] == "OWNER"
        assert data["gym_id"] == str(gym.id)
