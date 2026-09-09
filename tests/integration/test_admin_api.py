"""Integration tests for /api/v1/admin/* (sections 24, 33, 38)."""
from app.core.security import hash_password
from app.common.enums import GymStatus, UserRole
from app.gyms.models import Gym
from app.users.models import User


def login(client, email, password):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def make_gym(db_session, name="Gym A", slug="gym-a", status=GymStatus.ACTIVE):
    gym = Gym(name=name, slug=slug, status=status)
    db_session.add(gym)
    db_session.commit()
    db_session.refresh(gym)
    return gym


def make_owner(db_session, gym_id, email, password="OwnerPass123!"):
    user = User(
        email=email, full_name="Owner", hashed_password=hash_password(password),
        role=UserRole.OWNER, gym_id=gym_id,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


class TestGymCreation:
    def test_super_admin_can_create_gym(self, client, super_admin):
        token = login(client, "admin@test.com", "AdminPass123!")
        resp = client.post(
            "/api/v1/admin/gyms", json={"name": "Iron Paradise", "slug": "iron-paradise"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["name"] == "Iron Paradise"
        assert data["status"] == "ACTIVE"

    def test_duplicate_slug_rejected(self, client, super_admin, db_session):
        make_gym(db_session, slug="dup-slug")
        token = login(client, "admin@test.com", "AdminPass123!")
        resp = client.post(
            "/api/v1/admin/gyms", json={"name": "Another", "slug": "dup-slug"}, headers=auth_header(token)
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "GYM_SLUG_TAKEN"

    def test_invalid_slug_format_rejected(self, client, super_admin):
        token = login(client, "admin@test.com", "AdminPass123!")
        resp = client.post(
            "/api/v1/admin/gyms", json={"name": "Bad Slug Gym", "slug": "Not A Valid Slug!"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    def test_non_admin_cannot_create_gym(self, client, db_session):
        gym = make_gym(db_session)
        make_owner(db_session, gym.id, "owner1@test.com")
        token = login(client, "owner1@test.com", "OwnerPass123!")
        resp = client.post(
            "/api/v1/admin/gyms", json={"name": "Sneaky Gym", "slug": "sneaky"}, headers=auth_header(token)
        )
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "ROLE_NOT_PERMITTED"

    def test_unauthenticated_cannot_create_gym(self, client):
        resp = client.post("/api/v1/admin/gyms", json={"name": "X", "slug": "x"})
        assert resp.status_code == 401


class TestOwnerCreation:
    def test_super_admin_creates_owner_for_gym(self, client, super_admin, db_session):
        gym = make_gym(db_session)
        token = login(client, "admin@test.com", "AdminPass123!")
        resp = client.post(
            f"/api/v1/admin/gyms/{gym.id}/owners",
            json={"email": "newowner@test.com", "full_name": "New Owner", "password": "SecurePass1!"},
            headers=auth_header(token),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()["data"]
        assert data["email"] == "newowner@test.com"
        assert data["gym_id"] == str(gym.id)

        # And that owner can actually log in.
        owner_token = login(client, "newowner@test.com", "SecurePass1!")
        me = client.get("/api/v1/auth/me", headers=auth_header(owner_token)).json()["data"]
        assert me["role"] == "OWNER"
        assert me["gym_id"] == str(gym.id)

    def test_create_owner_for_nonexistent_gym_404(self, client, super_admin):
        import uuid

        token = login(client, "admin@test.com", "AdminPass123!")
        resp = client.post(
            f"/api/v1/admin/gyms/{uuid.uuid4()}/owners",
            json={"email": "x@test.com", "full_name": "X", "password": "SecurePass1!"},
            headers=auth_header(token),
        )
        assert resp.status_code == 404

    def test_duplicate_owner_email_rejected(self, client, super_admin, db_session):
        gym = make_gym(db_session)
        make_owner(db_session, gym.id, "taken@test.com")
        token = login(client, "admin@test.com", "AdminPass123!")
        resp = client.post(
            f"/api/v1/admin/gyms/{gym.id}/owners",
            json={"email": "taken@test.com", "full_name": "Dup", "password": "SecurePass1!"},
            headers=auth_header(token),
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "EMAIL_TAKEN"

    def test_owner_cannot_create_owner(self, client, db_session):
        gym = make_gym(db_session)
        make_owner(db_session, gym.id, "owner1@test.com")
        token = login(client, "owner1@test.com", "OwnerPass123!")
        resp = client.post(
            f"/api/v1/admin/gyms/{gym.id}/owners",
            json={"email": "x@test.com", "full_name": "X", "password": "SecurePass1!"},
            headers=auth_header(token),
        )
        assert resp.status_code == 403


class TestGymSuspension:
    def test_suspend_blocks_owner_login(self, client, super_admin, db_session):
        gym = make_gym(db_session)
        make_owner(db_session, gym.id, "owner1@test.com")
        admin_token = login(client, "admin@test.com", "AdminPass123!")

        # Owner can log in while active.
        login(client, "owner1@test.com", "OwnerPass123!")

        suspend_resp = client.post(f"/api/v1/admin/gyms/{gym.id}/suspend", headers=auth_header(admin_token))
        assert suspend_resp.status_code == 200
        assert suspend_resp.json()["data"]["status"] == "SUSPENDED"

        blocked_resp = client.post(
            "/api/v1/auth/login", json={"email": "owner1@test.com", "password": "OwnerPass123!"}
        )
        assert blocked_resp.status_code == 401
        assert blocked_resp.json()["error"]["code"] == "GYM_SUSPENDED"

    def test_reactivate_restores_login(self, client, super_admin, db_session):
        gym = make_gym(db_session, status=GymStatus.SUSPENDED)
        make_owner(db_session, gym.id, "owner1@test.com")
        admin_token = login(client, "admin@test.com", "AdminPass123!")

        blocked = client.post(
            "/api/v1/auth/login", json={"email": "owner1@test.com", "password": "OwnerPass123!"}
        )
        assert blocked.status_code == 401

        activate_resp = client.post(f"/api/v1/admin/gyms/{gym.id}/activate", headers=auth_header(admin_token))
        assert activate_resp.status_code == 200

        restored = client.post(
            "/api/v1/auth/login", json={"email": "owner1@test.com", "password": "OwnerPass123!"}
        )
        assert restored.status_code == 200

    def test_suspend_is_idempotent(self, client, super_admin, db_session):
        gym = make_gym(db_session)
        token = login(client, "admin@test.com", "AdminPass123!")
        r1 = client.post(f"/api/v1/admin/gyms/{gym.id}/suspend", headers=auth_header(token))
        r2 = client.post(f"/api/v1/admin/gyms/{gym.id}/suspend", headers=auth_header(token))
        assert r1.status_code == 200 and r2.status_code == 200
        assert r1.json()["data"]["status"] == r2.json()["data"]["status"] == "SUSPENDED"


class TestPlatformStats:
    def test_stats_counts_are_correct(self, client, super_admin, db_session):
        gym_a = make_gym(db_session, name="A", slug="a", status=GymStatus.ACTIVE)
        gym_b = make_gym(db_session, name="B", slug="b", status=GymStatus.SUSPENDED)
        make_owner(db_session, gym_a.id, "o1@test.com")
        make_owner(db_session, gym_a.id, "o2@test.com")
        make_owner(db_session, gym_b.id, "o3@test.com")

        token = login(client, "admin@test.com", "AdminPass123!")
        resp = client.get("/api/v1/admin/stats", headers=auth_header(token))
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total_gyms"] == 2
        assert data["active_gyms"] == 1
        assert data["total_owners"] == 3
        assert data["total_members"] == 0

    def test_non_admin_cannot_view_stats(self, client, db_session):
        gym = make_gym(db_session)
        make_owner(db_session, gym.id, "owner1@test.com")
        token = login(client, "owner1@test.com", "OwnerPass123!")
        resp = client.get("/api/v1/admin/stats", headers=auth_header(token))
        assert resp.status_code == 403


class TestAuditLogsAndSessionsAccess:
    def test_only_admin_sees_audit_logs(self, client, super_admin, db_session):
        gym = make_gym(db_session)
        make_owner(db_session, gym.id, "owner1@test.com")

        admin_token = login(client, "admin@test.com", "AdminPass123!")
        owner_token = login(client, "owner1@test.com", "OwnerPass123!")

        admin_resp = client.get("/api/v1/admin/audit-logs", headers=auth_header(admin_token))
        assert admin_resp.status_code == 200
        assert admin_resp.json()["data"]["total"] >= 1  # at least the OWNER_CREATED / LOGIN events

        owner_resp = client.get("/api/v1/admin/audit-logs", headers=auth_header(owner_token))
        assert owner_resp.status_code == 403

    def test_only_admin_sees_login_sessions(self, client, super_admin, db_session):
        gym = make_gym(db_session)
        make_owner(db_session, gym.id, "owner1@test.com")
        owner_token = login(client, "owner1@test.com", "OwnerPass123!")

        owner_resp = client.get("/api/v1/admin/login-sessions", headers=auth_header(owner_token))
        assert owner_resp.status_code == 403


class TestGymSelfService:
    def test_owner_sees_own_gym(self, client, db_session):
        gym = make_gym(db_session, name="My Gym", slug="my-gym")
        make_owner(db_session, gym.id, "owner1@test.com")
        token = login(client, "owner1@test.com", "OwnerPass123!")
        resp = client.get("/api/v1/gyms/me", headers=auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == str(gym.id)

    def test_super_admin_has_no_own_gym(self, client, super_admin):
        # SUPER_ADMIN has no gym_id, so require_tenant_gym_id must reject them
        # (they have no tenant context, and this route isn't for them anyway).
        token = login(client, "admin@test.com", "AdminPass123!")
        resp = client.get("/api/v1/gyms/me", headers=auth_header(token))
        assert resp.status_code == 403

    def test_owner_a_and_owner_b_see_different_gyms(self, client, db_session):
        """Core multi-tenancy check (section 33): two owners hitting the same
        'my gym' endpoint must never see each other's gym."""
        gym_a = make_gym(db_session, name="Gym A", slug="gym-aa")
        gym_b = make_gym(db_session, name="Gym B", slug="gym-bb")
        make_owner(db_session, gym_a.id, "ownera@test.com")
        make_owner(db_session, gym_b.id, "ownerb@test.com")

        token_a = login(client, "ownera@test.com", "OwnerPass123!")
        token_b = login(client, "ownerb@test.com", "OwnerPass123!")

        resp_a = client.get("/api/v1/gyms/me", headers=auth_header(token_a))
        resp_b = client.get("/api/v1/gyms/me", headers=auth_header(token_b))

        assert resp_a.json()["data"]["id"] == str(gym_a.id)
        assert resp_b.json()["data"]["id"] == str(gym_b.id)
        assert resp_a.json()["data"]["id"] != resp_b.json()["data"]["id"]
