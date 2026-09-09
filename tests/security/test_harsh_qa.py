"""
Harsh/adversarial QA pass (section 53). Covers attack vectors not already
exercised by earlier test files: expired JWT, DB-level duplicate constraint
enforcement, oversized payloads, and EXPIRED-membership edge cases.
"""
from datetime import date, datetime, timedelta, timezone

import pytest
from jose import jwt as jose_jwt
from sqlalchemy.exc import IntegrityError

from app.common.enums import GymStatus, MembershipStatus, UserRole
from app.core.config import settings
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


def setup_gym_owner(db_session, slug):
    gym = Gym(name="QA Gym", slug=slug, status=GymStatus.ACTIVE)
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


class TestExpiredJWT:
    def test_hand_crafted_expired_access_token_rejected(self, client, db_session):
        gym, owner = setup_gym_owner(db_session, "qa-expired-jwt")
        # Manually mint a token with exp in the past — simulates a real
        # access token that has simply expired, without waiting 15 minutes.
        payload = {
            "sub": str(owner.id), "gym_id": str(gym.id), "role": "OWNER", "session_id": "00000000-0000-0000-0000-000000000000",
            "type": "access", "iat": datetime.now(timezone.utc) - timedelta(hours=2),
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        }
        expired_token = jose_jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
        resp = client.get("/api/v1/auth/me", headers=auth_header(expired_token))
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "INVALID_TOKEN"

    def test_hand_crafted_expired_refresh_token_rejected(self, client, db_session):
        gym, owner = setup_gym_owner(db_session, "qa-expired-refresh")
        payload = {
            "sub": str(owner.id), "gym_id": str(gym.id), "role": "OWNER", "session_id": "00000000-0000-0000-0000-000000000000",
            "type": "refresh", "iat": datetime.now(timezone.utc) - timedelta(days=10),
            "exp": datetime.now(timezone.utc) - timedelta(days=3),
        }
        expired_refresh = jose_jwt.encode(payload, settings.JWT_REFRESH_SECRET, algorithm=settings.JWT_ALGORITHM)
        resp = client.post("/api/v1/auth/refresh", json={"refresh_token": expired_refresh})
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "INVALID_REFRESH_TOKEN"


class TestPrivilegeEscalationViaTamperedToken:
    def test_member_cannot_forge_owner_role_in_token(self, client, db_session):
        """A MEMBER cannot simply craft a token claiming role=OWNER, because
        the token is signed server-side — this proves the signature check
        actually matters, not just the role field's presence."""
        gym, owner = setup_gym_owner(db_session, "qa-privesc")
        member = Member(gym_id=gym.id, full_name="M")
        db_session.add(member)
        db_session.flush()
        member_user = User(
            email="privesc@test.com", full_name="M", hashed_password=hash_password("MemberPass123!"),
            role=UserRole.MEMBER, gym_id=gym.id,
        )
        db_session.add(member_user)
        db_session.commit()

        # Forge a token claiming OWNER role, signed with the WRONG secret
        # (attacker doesn't have JWT_SECRET) — this must be rejected outright.
        forged_payload = {
            "sub": str(member_user.id), "gym_id": str(gym.id), "role": "OWNER", "session_id": "00000000-0000-0000-0000-000000000000",
            "type": "access", "iat": datetime.now(timezone.utc), "exp": datetime.now(timezone.utc) + timedelta(minutes=15),
        }
        forged_token = jose_jwt.encode(forged_payload, "attacker-guessed-secret", algorithm=settings.JWT_ALGORITHM)
        resp = client.get("/api/v1/auth/me", headers=auth_header(forged_token))
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "INVALID_TOKEN"


class TestDBLevelDuplicateConstraints:
    def test_duplicate_membership_id_code_rejected_at_db_level(self, db_session):
        """Even bypassing the generator (e.g. a bug or direct insert), the
        UNIQUE constraint on membership_id_code must hold as the last line
        of defense."""
        gym, owner = setup_gym_owner(db_session, "qa-dup-code")
        member1 = Member(gym_id=gym.id, full_name="M1")
        member2 = Member(gym_id=gym.id, full_name="M2")
        plan = MembershipPlan(gym_id=gym.id, name="Monthly", duration_days=30, price=50)
        db_session.add_all([member1, member2, plan])
        db_session.flush()

        m1 = Membership(
            gym_id=gym.id, member_id=member1.id, plan_id=plan.id, membership_id_code="DUPCODE-00001",
            status=MembershipStatus.ACTIVE, start_date=date.today(), end_date=date.today() + timedelta(days=30),
        )
        db_session.add(m1)
        db_session.commit()

        m2 = Membership(
            gym_id=gym.id, member_id=member2.id, plan_id=plan.id, membership_id_code="DUPCODE-00001",  # SAME code
            status=MembershipStatus.ACTIVE, start_date=date.today(), end_date=date.today() + timedelta(days=30),
        )
        db_session.add(m2)
        with pytest.raises(IntegrityError):
            db_session.commit()
        db_session.rollback()


class TestOversizedPayloads:
    def test_extremely_long_member_name_rejected(self, client, db_session):
        gym, owner = setup_gym_owner(db_session, "qa-oversized")
        token = login(client, owner.email, "OwnerPass123!")
        huge_name = "A" * 10000  # far beyond the 255-char schema limit
        resp = client.post("/api/v1/members", json={"full_name": huge_name}, headers=auth_header(token))
        assert resp.status_code == 422

    def test_extremely_long_notes_field_rejected(self, client, db_session):
        gym, owner = setup_gym_owner(db_session, "qa-oversized-notes")
        member = Member(gym_id=gym.id, full_name="M")
        db_session.add(member)
        db_session.flush()
        member_user = User(
            email="oversized-notes@test.com", full_name="M", hashed_password=hash_password("MemberPass123!"),
            role=UserRole.MEMBER, gym_id=gym.id,
        )
        db_session.add(member_user)
        db_session.flush()
        member.user_id = member_user.id
        plan = MembershipPlan(gym_id=gym.id, name="Monthly", duration_days=30, price=50)
        db_session.add(plan)
        db_session.flush()
        db_session.add(Membership(
            gym_id=gym.id, member_id=member.id, plan_id=plan.id, membership_id_code="OVERSIZE-001",
            status=MembershipStatus.ACTIVE, start_date=date.today(), end_date=date.today() + timedelta(days=30),
        ))
        db_session.commit()

        token = login(client, "oversized-notes@test.com", "MemberPass123!")
        session_resp = client.post("/api/v1/workouts/sessions", json={}, headers=auth_header(token))
        session_id = session_resp.json()["data"]["id"]

        exercise = None
        from app.workouts.models import Exercise
        exercise = Exercise(gym_id=gym.id, name="Deadlift")
        db_session.add(exercise)
        db_session.commit()
        db_session.refresh(exercise)

        huge_notes = "x" * 5000
        resp = client.post(
            f"/api/v1/workouts/sessions/{session_id}/logs",
            json={"exercise_id": str(exercise.id), "set_number": 1, "reps": 5, "notes": huge_notes},
            headers=auth_header(token),
        )
        assert resp.status_code == 422


class TestExpiredMembershipTerminalState:
    def test_expired_membership_blocks_tracking_same_as_restricted(self, client, db_session):
        gym, owner = setup_gym_owner(db_session, "qa-expired-membership")
        member = Member(gym_id=gym.id, full_name="M")
        db_session.add(member)
        db_session.flush()
        member_user = User(
            email="expired-member@test.com", full_name="M", hashed_password=hash_password("MemberPass123!"),
            role=UserRole.MEMBER, gym_id=gym.id,
        )
        db_session.add(member_user)
        db_session.flush()
        member.user_id = member_user.id
        plan = MembershipPlan(gym_id=gym.id, name="Monthly", duration_days=30, price=50)
        db_session.add(plan)
        db_session.flush()
        db_session.add(Membership(
            gym_id=gym.id, member_id=member.id, plan_id=plan.id, membership_id_code="EXPIRED-001",
            status=MembershipStatus.EXPIRED, start_date=date.today() - timedelta(days=60), end_date=date.today() - timedelta(days=30),
        ))
        db_session.commit()

        token = login(client, "expired-member@test.com", "MemberPass123!")
        # A member who reaches EXPIRED only gets there by staying RESTRICTED
        # for 30+ days — so EXPIRED must remain blocked, not un-block them.
        # (This was a real bug found during this QA pass: assert_not_restricted
        # originally checked ONLY the RESTRICTED status, so aging into EXPIRED
        # would have incorrectly un-blocked tracking. Fixed in
        # app.memberships.lifecycle.blocks_new_tracking.)
        resp = client.post("/api/v1/progress", json={"weight_kg": "70"}, headers=auth_header(token))
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "MEMBERSHIP_RESTRICTED"

    def test_cannot_pay_expired_membership(self, client, db_session):
        gym, owner = setup_gym_owner(db_session, "qa-expired-pay")
        member = Member(gym_id=gym.id, full_name="M")
        plan = MembershipPlan(gym_id=gym.id, name="Monthly", duration_days=30, price=50)
        db_session.add_all([member, plan])
        db_session.flush()
        membership = Membership(
            gym_id=gym.id, member_id=member.id, plan_id=plan.id, membership_id_code="EXPPAY-001",
            status=MembershipStatus.EXPIRED, start_date=date.today() - timedelta(days=60), end_date=date.today() - timedelta(days=30),
        )
        db_session.add(membership)
        db_session.commit()

        token = login(client, owner.email, "OwnerPass123!")
        resp = client.post(
            "/api/v1/payments", json={"membership_id": str(membership.id), "amount": "50"}, headers=auth_header(token)
        )
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "MEMBERSHIP_TERMINAL_STATE"


class TestInvalidDateHandling:
    def test_malformed_date_string_rejected(self, client, db_session):
        gym, owner = setup_gym_owner(db_session, "qa-bad-date")
        member = Member(gym_id=gym.id, full_name="M")
        plan = MembershipPlan(gym_id=gym.id, name="Monthly", duration_days=30, price=50)
        db_session.add_all([member, plan])
        db_session.commit()

        token = login(client, owner.email, "OwnerPass123!")
        resp = client.post(
            "/api/v1/memberships",
            json={"member_id": str(member.id), "plan_id": str(plan.id), "start_date": "not-a-date"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422

    def test_unpadded_date_rejected(self, client, db_session):
        gym, owner = setup_gym_owner(db_session, "qa-unpadded-date")
        member = Member(gym_id=gym.id, full_name="M")
        plan = MembershipPlan(gym_id=gym.id, name="Monthly", duration_days=30, price=50)
        db_session.add_all([member, plan])
        db_session.commit()

        token = login(client, owner.email, "OwnerPass123!")
        resp = client.post(
            "/api/v1/memberships",
            json={"member_id": str(member.id), "plan_id": str(plan.id), "start_date": "2026-1-1"},
            headers=auth_header(token),
        )
        assert resp.status_code == 422


class TestRepeatedIdenticalRequests:
    def test_two_identical_payment_requests_both_recorded_independently(self, client, db_session):
        """No idempotency-key mechanism exists in V1 (not in spec) — this
        pins down the CURRENT behavior: double-submitting creates two
        payments and renews end_date twice. Documented, not silently assumed."""
        gym, owner = setup_gym_owner(db_session, "qa-repeat-payment")
        member = Member(gym_id=gym.id, full_name="M")
        plan = MembershipPlan(gym_id=gym.id, name="Monthly", duration_days=30, price=50)
        db_session.add_all([member, plan])
        db_session.flush()
        membership = Membership(
            gym_id=gym.id, member_id=member.id, plan_id=plan.id, membership_id_code="REPEAT-001",
            status=MembershipStatus.ACTIVE, start_date=date.today(), end_date=date.today() + timedelta(days=30),
        )
        db_session.add(membership)
        db_session.commit()

        token = login(client, owner.email, "OwnerPass123!")
        body = {"membership_id": str(membership.id), "amount": "50.00", "payment_date": date.today().isoformat()}
        resp1 = client.post("/api/v1/payments", json=body, headers=auth_header(token))
        resp2 = client.post("/api/v1/payments", json=body, headers=auth_header(token))
        assert resp1.status_code == 201
        assert resp2.status_code == 201
        assert resp1.json()["data"]["id"] != resp2.json()["data"]["id"]

        from app.payments.models import Payment
        count = db_session.query(Payment).filter(Payment.membership_id == membership.id).count()
        assert count == 2
