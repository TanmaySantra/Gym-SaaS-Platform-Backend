"""Integration tests for workout/progress tracking and the RESTRICTED
enforcement from section 10 — the most important behavioral test in this
batch: the backend must reject tracking attempts, not just hide UI buttons."""
from datetime import date, timedelta

from app.common.enums import GymStatus, MembershipStatus, UserRole
from app.core.security import hash_password
from app.gyms.models import Gym
from app.members.models import Member
from app.memberships.models import Membership, MembershipPlan
from app.users.models import User
from app.workouts.models import Exercise


def login(client, email, password):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def setup_full_stack(db_session, slug, membership_status=MembershipStatus.ACTIVE, end_date=None):
    """Gym + Owner + Member (linked to a login) + an ACTIVE-or-otherwise membership."""
    gym = Gym(name="Track Gym", slug=slug, status=GymStatus.ACTIVE)
    db_session.add(gym)
    db_session.flush()

    owner = User(
        email=f"owner-{slug}@test.com", full_name="Owner", hashed_password=hash_password("OwnerPass123!"),
        role=UserRole.OWNER, gym_id=gym.id,
    )
    member = Member(gym_id=gym.id, full_name="Tracked Member")
    db_session.add_all([owner, member])
    db_session.flush()

    member_user = User(
        email=f"member-{slug}@test.com", full_name=member.full_name,
        hashed_password=hash_password("MemberPass123!"), role=UserRole.MEMBER, gym_id=gym.id,
    )
    db_session.add(member_user)
    db_session.flush()
    member.user_id = member_user.id

    plan = MembershipPlan(gym_id=gym.id, name="Monthly", duration_days=30, price=50)
    db_session.add(plan)
    db_session.flush()

    resolved_end = end_date or (date.today() + timedelta(days=10))
    membership = Membership(
        gym_id=gym.id, member_id=member.id, plan_id=plan.id, membership_id_code=f"{slug.upper()}-00001",
        status=membership_status, start_date=resolved_end - timedelta(days=20), end_date=resolved_end,
    )
    db_session.add(membership)

    exercise = Exercise(gym_id=gym.id, name="Bench Press", muscle_group="Chest")
    db_session.add(exercise)

    db_session.commit()
    for obj in (gym, owner, member, member_user, plan, membership, exercise):
        db_session.refresh(obj)
    return {
        "gym": gym, "owner": owner, "member": member, "member_user": member_user,
        "plan": plan, "membership": membership, "exercise": exercise,
    }


class TestWorkoutTrackingRestriction:
    def test_active_member_can_start_session_and_log_sets(self, client, db_session):
        ctx = setup_full_stack(db_session, "active-track")
        token = login(client, ctx["member_user"].email, "MemberPass123!")

        start_resp = client.post("/api/v1/workouts/sessions", json={}, headers=auth_header(token))
        assert start_resp.status_code == 201, start_resp.text
        session_id = start_resp.json()["data"]["id"]

        log_resp = client.post(
            f"/api/v1/workouts/sessions/{session_id}/logs",
            json={"exercise_id": str(ctx["exercise"].id), "set_number": 1, "reps": 10, "weight_kg": "50"},
            headers=auth_header(token),
        )
        assert log_resp.status_code == 201, log_resp.text

    def test_restricted_member_cannot_start_session(self, client, db_session):
        ctx = setup_full_stack(db_session, "restricted-track", membership_status=MembershipStatus.RESTRICTED)
        token = login(client, ctx["member_user"].email, "MemberPass123!")

        resp = client.post("/api/v1/workouts/sessions", json={}, headers=auth_header(token))
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "MEMBERSHIP_RESTRICTED"

    def test_restricted_member_cannot_log_sets_on_existing_session(self, client, db_session):
        """A member who started a session while ACTIVE, then became RESTRICTED
        mid-workout, must be blocked from adding NEW logs (section 10)."""
        ctx = setup_full_stack(db_session, "mid-restrict-track")
        token = login(client, ctx["member_user"].email, "MemberPass123!")

        start_resp = client.post("/api/v1/workouts/sessions", json={}, headers=auth_header(token))
        session_id = start_resp.json()["data"]["id"]

        # Membership gets restricted mid-session (e.g. Celery Beat runs).
        ctx["membership"].status = MembershipStatus.RESTRICTED
        db_session.commit()

        log_resp = client.post(
            f"/api/v1/workouts/sessions/{session_id}/logs",
            json={"exercise_id": str(ctx["exercise"].id), "set_number": 1, "reps": 10},
            headers=auth_header(token),
        )
        assert log_resp.status_code == 403
        assert log_resp.json()["error"]["code"] == "MEMBERSHIP_RESTRICTED"

    def test_restricted_member_can_still_view_historical_sessions(self, client, db_session):
        """Section 10: restriction blocks NEW data, not access to existing
        historical data."""
        ctx = setup_full_stack(db_session, "history-track")
        token = login(client, ctx["member_user"].email, "MemberPass123!")

        start_resp = client.post("/api/v1/workouts/sessions", json={}, headers=auth_header(token))
        session_id = start_resp.json()["data"]["id"]

        ctx["membership"].status = MembershipStatus.RESTRICTED
        db_session.commit()

        list_resp = client.get("/api/v1/workouts/sessions", headers=auth_header(token))
        assert list_resp.status_code == 200
        assert list_resp.json()["data"]["total"] == 1

        get_resp = client.get(f"/api/v1/workouts/sessions/{session_id}", headers=auth_header(token))
        assert get_resp.status_code == 200

    def test_restricted_member_can_still_complete_an_in_progress_session(self, client, db_session):
        """Completing existing work is not 'creating new' tracking data."""
        ctx = setup_full_stack(db_session, "complete-track")
        token = login(client, ctx["member_user"].email, "MemberPass123!")

        start_resp = client.post("/api/v1/workouts/sessions", json={}, headers=auth_header(token))
        session_id = start_resp.json()["data"]["id"]

        ctx["membership"].status = MembershipStatus.RESTRICTED
        db_session.commit()

        complete_resp = client.post(
            f"/api/v1/workouts/sessions/{session_id}/complete", headers=auth_header(token)
        )
        assert complete_resp.status_code == 200
        assert complete_resp.json()["data"]["status"] == "COMPLETED"

    def test_owner_cannot_start_a_workout_session(self, client, db_session):
        ctx = setup_full_stack(db_session, "owner-workout-track")
        token = login(client, ctx["owner"].email, "OwnerPass123!")
        resp = client.post("/api/v1/workouts/sessions", json={}, headers=auth_header(token))
        assert resp.status_code == 403


class TestProgressTrackingRestriction:
    def test_active_member_can_record_progress(self, client, db_session):
        ctx = setup_full_stack(db_session, "active-progress")
        token = login(client, ctx["member_user"].email, "MemberPass123!")
        resp = client.post("/api/v1/progress", json={"weight_kg": "82.5"}, headers=auth_header(token))
        assert resp.status_code == 201, resp.text

    def test_restricted_member_cannot_record_progress(self, client, db_session):
        ctx = setup_full_stack(db_session, "restricted-progress", membership_status=MembershipStatus.RESTRICTED)
        token = login(client, ctx["member_user"].email, "MemberPass123!")
        resp = client.post("/api/v1/progress", json={"weight_kg": "80"}, headers=auth_header(token))
        assert resp.status_code == 403
        assert resp.json()["error"]["code"] == "MEMBERSHIP_RESTRICTED"

    def test_no_measurement_provided_rejected(self, client, db_session):
        ctx = setup_full_stack(db_session, "empty-progress")
        token = login(client, ctx["member_user"].email, "MemberPass123!")
        resp = client.post("/api/v1/progress", json={}, headers=auth_header(token))
        assert resp.status_code == 422
        assert resp.json()["error"]["code"] == "NO_MEASUREMENT_PROVIDED"

    def test_restricted_member_can_still_view_historical_progress(self, client, db_session):
        ctx = setup_full_stack(db_session, "restricted-progress-view")
        token = login(client, ctx["member_user"].email, "MemberPass123!")

        client.post("/api/v1/progress", json={"weight_kg": "82.5"}, headers=auth_header(token))

        ctx["membership"].status = MembershipStatus.RESTRICTED
        db_session.commit()

        resp = client.get("/api/v1/progress", headers=auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 1

    def test_owner_can_view_own_gym_member_progress(self, client, db_session):
        ctx = setup_full_stack(db_session, "owner-view-progress")
        member_token = login(client, ctx["member_user"].email, "MemberPass123!")
        client.post("/api/v1/progress", json={"weight_kg": "77"}, headers=auth_header(member_token))

        owner_token = login(client, ctx["owner"].email, "OwnerPass123!")
        resp = client.get(f"/api/v1/progress/members/{ctx['member'].id}", headers=auth_header(owner_token))
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 1

    def test_owner_b_cannot_view_gym_a_member_progress(self, client, db_session):
        ctx_a = setup_full_stack(db_session, "cross-progress-a")
        ctx_b = setup_full_stack(db_session, "cross-progress-b")
        token_b = login(client, ctx_b["owner"].email, "OwnerPass123!")

        resp = client.get(f"/api/v1/progress/members/{ctx_a['member'].id}", headers=auth_header(token_b))
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "MEMBER_NOT_FOUND"


class TestAttendance:
    def test_owner_records_attendance(self, client, db_session):
        ctx = setup_full_stack(db_session, "attend-basic")
        token = login(client, ctx["owner"].email, "OwnerPass123!")
        resp = client.post(
            "/api/v1/attendance", json={"member_id": str(ctx["member"].id)}, headers=auth_header(token)
        )
        assert resp.status_code == 201, resp.text

    def test_duplicate_attendance_same_day_rejected(self, client, db_session):
        ctx = setup_full_stack(db_session, "attend-dup")
        token = login(client, ctx["owner"].email, "OwnerPass123!")
        client.post("/api/v1/attendance", json={"member_id": str(ctx["member"].id)}, headers=auth_header(token))
        resp = client.post("/api/v1/attendance", json={"member_id": str(ctx["member"].id)}, headers=auth_header(token))
        assert resp.status_code == 409
        assert resp.json()["error"]["code"] == "ATTENDANCE_ALREADY_RECORDED"

    def test_owner_a_cannot_record_attendance_for_member_b(self, client, db_session):
        """IDOR via request body: gym_id is correct (owner A's own), but
        member_id points at gym B's member (section 33/34)."""
        ctx_a = setup_full_stack(db_session, "attend-cross-a")
        ctx_b = setup_full_stack(db_session, "attend-cross-b")
        token_a = login(client, ctx_a["owner"].email, "OwnerPass123!")

        resp = client.post(
            "/api/v1/attendance", json={"member_id": str(ctx_b["member"].id)}, headers=auth_header(token_a)
        )
        assert resp.status_code == 404
        assert resp.json()["error"]["code"] == "MEMBER_NOT_FOUND"

    def test_member_sees_own_attendance_summary(self, client, db_session):
        ctx = setup_full_stack(db_session, "attend-summary")
        owner_token = login(client, ctx["owner"].email, "OwnerPass123!")
        client.post("/api/v1/attendance", json={"member_id": str(ctx["member"].id)}, headers=auth_header(owner_token))

        member_token = login(client, ctx["member_user"].email, "MemberPass123!")
        resp = client.get("/api/v1/attendance/me/summary", headers=auth_header(member_token))
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total_days_recorded"] == 1
        assert data["days_present_last_30"] == 1

    def test_member_cannot_record_own_attendance(self, client, db_session):
        ctx = setup_full_stack(db_session, "attend-member-block")
        token = login(client, ctx["member_user"].email, "MemberPass123!")
        resp = client.post(
            "/api/v1/attendance", json={"member_id": str(ctx["member"].id)}, headers=auth_header(token)
        )
        assert resp.status_code == 403
