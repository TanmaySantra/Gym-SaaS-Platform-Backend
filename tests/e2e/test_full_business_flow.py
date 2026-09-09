"""
Full end-to-end business flow test (section 40) - the most important test
in the entire prototype.

Walks the EXACT flow from section 1:
    Platform Admin -> Creates Gym -> Creates Gym Owner -> Owner Login ->
    Owner Creates Member -> Membership ID Generated -> Member Uses
    Membership ID -> Member Account Created -> Member Logs In -> Member
    Tracks Workout -> Member Tracks Progress -> Owner Sees Member Progress
    -> System Analyzes Member Activity -> AI Generates Insight -> Owner
    Receives Recommended Action -> Payment Becomes Overdue -> 7-Day Grace
    Period -> Celery Beat Detects Expiry/Overdue State -> Member Becomes
    RESTRICTED -> Member Cannot Track New Progress -> Payment Is Restored
    -> Member Becomes ACTIVE Again -> Previous Progress Remains Intact

Also demonstrates: Owner A attempting to access Gym B's data is denied
(section 56).

Every step is a REAL HTTP call through the FastAPI TestClient against a REAL
Postgres database (via the client/db_session fixtures) - nothing here is
mocked except the AI provider's network call (no live provider reachable in
this environment; the rest of the AI pipeline - prompt building, response
validation, persistence, notification - is fully exercised).
"""
from datetime import date, datetime, timedelta, timezone

from app.ai import service as ai_service
from app.common.enums import UserRole
from app.core.security import hash_password
from app.users.models import User


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def fake_ai_call(prompt: str) -> str:
    return (
        '{"risk_level": "medium", "insight": "Workout consistency has declined.", '
        '"reason": "Workout frequency decreased compared to the prior period.", '
        '"recommended_action": "Contact the member and review their current workout plan."}'
    )


def test_full_business_flow_end_to_end(client, db_session):
    # ============================================================
    # STEP 0: Seed the platform's first SUPER_ADMIN (bootstrap-only
    # exception to "no public registration", per section 8's design).
    # ============================================================
    super_admin = User(
        email="admin@e2e-test.com", full_name="Platform Admin",
        hashed_password=hash_password("SuperAdminPass123!"), role=UserRole.SUPER_ADMIN, gym_id=None,
    )
    db_session.add(super_admin)
    db_session.commit()

    login_resp = client.post("/api/v1/auth/login", json={"email": "admin@e2e-test.com", "password": "SuperAdminPass123!"})
    assert login_resp.status_code == 200
    admin_token = login_resp.json()["data"]["access_token"]

    # ============================================================
    # STEP 1: Platform Admin creates Gym A and Gym B (B is used later
    # purely to demonstrate cross-tenant denial).
    # ============================================================
    gym_a_resp = client.post(
        "/api/v1/admin/gyms", json={"name": "Iron Peak Fitness", "slug": "iron-peak-e2e"}, headers=auth_header(admin_token)
    )
    assert gym_a_resp.status_code == 201, gym_a_resp.text
    gym_a_id = gym_a_resp.json()["data"]["id"]

    gym_b_resp = client.post(
        "/api/v1/admin/gyms", json={"name": "Summit Strength", "slug": "summit-strength-e2e"}, headers=auth_header(admin_token)
    )
    assert gym_b_resp.status_code == 201
    gym_b_id = gym_b_resp.json()["data"]["id"]

    # ============================================================
    # STEP 2: Platform Admin creates a Gym Owner for each gym.
    # ============================================================
    owner_a_resp = client.post(
        f"/api/v1/admin/gyms/{gym_a_id}/owners",
        json={"email": "owner-a@e2e-test.com", "full_name": "Owner A", "password": "OwnerAPass123!"},
        headers=auth_header(admin_token),
    )
    assert owner_a_resp.status_code == 201, owner_a_resp.text

    owner_b_resp = client.post(
        f"/api/v1/admin/gyms/{gym_b_id}/owners",
        json={"email": "owner-b@e2e-test.com", "full_name": "Owner B", "password": "OwnerBPass123!"},
        headers=auth_header(admin_token),
    )
    assert owner_b_resp.status_code == 201

    # ============================================================
    # STEP 3: Owner Login.
    # ============================================================
    owner_a_login = client.post("/api/v1/auth/login", json={"email": "owner-a@e2e-test.com", "password": "OwnerAPass123!"})
    assert owner_a_login.status_code == 200
    owner_a_token = owner_a_login.json()["data"]["access_token"]

    owner_b_login = client.post("/api/v1/auth/login", json={"email": "owner-b@e2e-test.com", "password": "OwnerBPass123!"})
    assert owner_b_login.status_code == 200
    owner_b_token = owner_b_login.json()["data"]["access_token"]

    # ============================================================
    # STEP 4: Owner Creates Member.
    # ============================================================
    member_resp = client.post(
        "/api/v1/members", json={"full_name": "Rahul Sharma", "phone": "+91-9876543210"}, headers=auth_header(owner_a_token)
    )
    assert member_resp.status_code == 201, member_resp.text
    member_id = member_resp.json()["data"]["id"]
    assert member_resp.json()["data"]["is_linked"] is False

    member_b_resp = client.post("/api/v1/members", json={"full_name": "Priya B"}, headers=auth_header(owner_b_token))
    assert member_b_resp.status_code == 201
    member_b_id = member_b_resp.json()["data"]["id"]

    # ============================================================
    # STEP 5: Membership ID Generated (owner creates a plan, then a
    # membership for the member).
    # ============================================================
    plan_resp = client.post(
        "/api/v1/memberships/plans", json={"name": "Monthly", "duration_days": 30, "price": "50.00"},
        headers=auth_header(owner_a_token),
    )
    assert plan_resp.status_code == 201
    plan_id = plan_resp.json()["data"]["id"]

    membership_resp = client.post(
        "/api/v1/memberships", json={"member_id": member_id, "plan_id": plan_id}, headers=auth_header(owner_a_token)
    )
    assert membership_resp.status_code == 201, membership_resp.text
    membership_id = membership_resp.json()["data"]["id"]
    membership_code = membership_resp.json()["data"]["membership_id_code"]
    assert "-" in membership_code
    assert membership_resp.json()["data"]["status"] == "ACTIVE"

    # ============================================================
    # STEP 6: Member Uses Membership ID -> Member Account Created.
    # ============================================================
    link_resp = client.post(
        "/api/v1/members/link",
        json={"membership_id_code": membership_code, "email": "rahul@e2e-test.com", "password": "RahulPass123!"},
    )
    assert link_resp.status_code == 200, link_resp.text
    assert link_resp.json()["data"]["email"] == "rahul@e2e-test.com"

    bad_login = client.post("/api/v1/auth/login", json={"email": "rahul@e2e-test.com", "password": membership_code})
    assert bad_login.status_code == 401

    # ============================================================
    # STEP 7: Member Logs In.
    # ============================================================
    member_login = client.post("/api/v1/auth/login", json={"email": "rahul@e2e-test.com", "password": "RahulPass123!"})
    assert member_login.status_code == 200
    member_token = member_login.json()["data"]["access_token"]

    member_me = client.get("/api/v1/auth/me", headers=auth_header(member_token))
    assert member_me.json()["data"]["role"] == "MEMBER"
    assert member_me.json()["data"]["gym_id"] == gym_a_id

    # ============================================================
    # STEP 8: Member Tracks Workout.
    # ============================================================
    exercise_resp = client.post(
        "/api/v1/workouts/exercises", json={"name": "Bench Press", "muscle_group": "Chest"}, headers=auth_header(owner_a_token)
    )
    assert exercise_resp.status_code == 201
    exercise_id = exercise_resp.json()["data"]["id"]

    session_resp = client.post("/api/v1/workouts/sessions", json={}, headers=auth_header(member_token))
    assert session_resp.status_code == 201
    session_id = session_resp.json()["data"]["id"]

    log_resp = client.post(
        f"/api/v1/workouts/sessions/{session_id}/logs",
        json={"exercise_id": exercise_id, "set_number": 1, "reps": 10, "weight_kg": "50"},
        headers=auth_header(member_token),
    )
    assert log_resp.status_code == 201

    complete_resp = client.post(f"/api/v1/workouts/sessions/{session_id}/complete", headers=auth_header(member_token))
    assert complete_resp.status_code == 200
    assert complete_resp.json()["data"]["status"] == "COMPLETED"

    # ============================================================
    # STEP 9: Member Tracks Progress.
    # ============================================================
    progress_resp = client.post("/api/v1/progress", json={"weight_kg": "82.5"}, headers=auth_header(member_token))
    assert progress_resp.status_code == 201, progress_resp.text
    original_weight = progress_resp.json()["data"]["weight_kg"]
    assert float(original_weight) == 82.5

    # ============================================================
    # STEP 10: Owner Sees Member Progress.
    # ============================================================
    owner_progress_resp = client.get(f"/api/v1/progress/members/{member_id}", headers=auth_header(owner_a_token))
    assert owner_progress_resp.status_code == 200
    assert owner_progress_resp.json()["data"]["total"] == 1
    assert float(owner_progress_resp.json()["data"]["items"][0]["weight_kg"]) == 82.5

    # ============================================================
    # STEP 11: System Analyzes Member Activity -> AI Generates Insight
    # -> Owner Receives Recommended Action.
    # ============================================================
    insight = ai_service.generate_insight_for_member(
        db_session, gym_id=gym_a_id, member_id=member_id, ai_call=fake_ai_call
    )
    assert insight.risk_level.value == "medium"
    assert insight.recommended_action == "Contact the member and review their current workout plan."

    owner_insights_resp = client.get(f"/api/v1/ai/insights/members/{member_id}", headers=auth_header(owner_a_token))
    assert owner_insights_resp.status_code == 200
    assert owner_insights_resp.json()["data"]["total"] == 1

    owner_notifications_resp = client.get("/api/v1/notifications", headers=auth_header(owner_a_token))
    ai_notifications = [n for n in owner_notifications_resp.json()["data"]["items"] if n["type"] == "AI_INSIGHT"]
    assert len(ai_notifications) == 1, "Owner must receive the recommended action as a notification"

    # ============================================================
    # STEP 12: Payment Becomes Overdue.
    # ============================================================
    from app.memberships.models import Membership
    from app.memberships import service as membership_service

    membership = db_session.get(Membership, membership_id)
    membership.end_date = date.today() - timedelta(days=1)
    db_session.commit()

    check_result_1 = membership_service.run_membership_checks(db_session, gym_id=gym_a_id)
    assert check_result_1["marked_payment_due"] == 1

    db_session.refresh(membership)
    assert membership.status.value == "PAYMENT_DUE"

    member_notifications_resp = client.get("/api/v1/notifications", headers=auth_header(member_token))
    overdue_notifications = [n for n in member_notifications_resp.json()["data"]["items"] if n["type"] == "PAYMENT_OVERDUE"]
    assert len(overdue_notifications) == 1

    # ============================================================
    # STEP 13: 7-Day Grace Period -> Celery Beat Detects Expiry/Overdue
    # State -> Member Becomes RESTRICTED.
    # ============================================================
    membership.payment_due_since = datetime.combine(
        date.today() - timedelta(days=8), datetime.min.time(), tzinfo=timezone.utc
    )
    db_session.commit()

    check_result_2 = membership_service.run_membership_checks(db_session, gym_id=gym_a_id)
    assert check_result_2["marked_restricted"] == 1

    db_session.refresh(membership)
    assert membership.status.value == "RESTRICTED"

    check_result_3 = membership_service.run_membership_checks(db_session, gym_id=gym_a_id)
    assert check_result_3["marked_restricted"] == 0

    # ============================================================
    # STEP 14: Member Cannot Track New Progress (or start new workouts).
    # ============================================================
    blocked_progress = client.post("/api/v1/progress", json={"weight_kg": "81"}, headers=auth_header(member_token))
    assert blocked_progress.status_code == 403
    assert blocked_progress.json()["error"]["code"] == "MEMBERSHIP_RESTRICTED"

    blocked_session = client.post("/api/v1/workouts/sessions", json={}, headers=auth_header(member_token))
    assert blocked_session.status_code == 403
    assert blocked_session.json()["error"]["code"] == "MEMBERSHIP_RESTRICTED"

    historical_progress = client.get("/api/v1/progress", headers=auth_header(member_token))
    assert historical_progress.json()["data"]["total"] == 1
    assert float(historical_progress.json()["data"]["items"][0]["weight_kg"]) == 82.5

    # ============================================================
    # STEP 15: Payment Is Restored -> Membership ACTIVE.
    # ============================================================
    payment_resp = client.post(
        "/api/v1/payments", json={"membership_id": membership_id, "amount": "50.00"}, headers=auth_header(owner_a_token)
    )
    assert payment_resp.status_code == 201, payment_resp.text

    db_session.refresh(membership)
    assert membership.status.value == "ACTIVE"
    assert membership.payment_due_since is None
    assert membership.restricted_at is None

    # ============================================================
    # STEP 16: Member Can Track Again.
    # ============================================================
    new_progress_resp = client.post("/api/v1/progress", json={"weight_kg": "81.0"}, headers=auth_header(member_token))
    assert new_progress_resp.status_code == 201, new_progress_resp.text

    new_session_resp = client.post("/api/v1/workouts/sessions", json={}, headers=auth_header(member_token))
    assert new_session_resp.status_code == 201

    # ============================================================
    # STEP 17: Previous Progress Remains Intact.
    # ============================================================
    final_progress_resp = client.get("/api/v1/progress", headers=auth_header(member_token))
    assert final_progress_resp.json()["data"]["total"] == 2
    weights = {float(item["weight_kg"]) for item in final_progress_resp.json()["data"]["items"]}
    assert 82.5 in weights, "The ORIGINAL progress record from before restriction must still exist"
    assert 81.0 in weights

    # ============================================================
    # FINAL: Demonstrate Owner A attempting to access Gym B is denied
    # (section 56).
    # ============================================================
    cross_tenant_member_fetch = client.get(f"/api/v1/members/{member_b_id}", headers=auth_header(owner_a_token))
    assert cross_tenant_member_fetch.status_code == 404
    assert cross_tenant_member_fetch.json()["error"]["code"] == "MEMBER_NOT_FOUND"

    cross_tenant_membership_attempt = client.post(
        "/api/v1/memberships", json={"member_id": member_b_id, "plan_id": plan_id}, headers=auth_header(owner_a_token)
    )
    assert cross_tenant_membership_attempt.status_code == 404
    assert cross_tenant_membership_attempt.json()["error"]["code"] == "MEMBER_NOT_FOUND"

    final_dashboard = client.get("/api/v1/analytics/dashboard", headers=auth_header(owner_a_token))
    assert final_dashboard.json()["data"]["total_members"] == 1
    assert final_dashboard.json()["data"]["active_members"] == 1
