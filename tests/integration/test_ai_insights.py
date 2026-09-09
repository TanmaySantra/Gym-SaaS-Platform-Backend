"""
Integration tests for the AI insight pipeline (sections 19/20/25/37).

Uses injected fake `ai_call` functions instead of a real provider — the
provider boundary (app.ai.client.call_ai_provider) is a single function
specifically so this substitution is trivial and requires no network access
or mocking framework.
"""
from datetime import date, timedelta

import pytest

from app.ai import service as ai_service
from app.ai.client import AIProviderError
from app.common.enums import GymStatus, MembershipStatus, UserRole
from app.core.security import hash_password
from app.gyms.models import Gym
from app.members.models import Member
from app.memberships.models import Membership, MembershipPlan
from app.users.models import User
from app.workouts.models import Exercise, WorkoutSession
from app.common.enums import WorkoutSessionStatus


def login(client, email, password):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def setup_stack(db_session, slug):
    gym = Gym(name="AI Gym", slug=slug, status=GymStatus.ACTIVE)
    db_session.add(gym)
    db_session.flush()
    owner = User(
        email=f"owner-{slug}@test.com", full_name="Owner", hashed_password=hash_password("OwnerPass123!"),
        role=UserRole.OWNER, gym_id=gym.id,
    )
    member = Member(gym_id=gym.id, full_name="Ana Rivera")
    db_session.add_all([owner, member])
    db_session.flush()
    member_user = User(
        email=f"member-{slug}@test.com", full_name=member.full_name, hashed_password=hash_password("MemberPass123!"),
        role=UserRole.MEMBER, gym_id=gym.id,
    )
    db_session.add(member_user)
    db_session.flush()
    member.user_id = member_user.id

    plan = MembershipPlan(gym_id=gym.id, name="Monthly", duration_days=30, price=50)
    db_session.add(plan)
    db_session.flush()
    membership = Membership(
        gym_id=gym.id, member_id=member.id, plan_id=plan.id, membership_id_code=f"{slug.upper()}-00001",
        status=MembershipStatus.ACTIVE, start_date=date.today() - timedelta(days=10), end_date=date.today() + timedelta(days=20),
    )
    db_session.add(membership)
    db_session.commit()
    for obj in (gym, owner, member, member_user, plan, membership):
        db_session.refresh(obj)
    return {"gym": gym, "owner": owner, "member": member, "member_user": member_user, "membership": membership}


def fake_ai_call_valid(prompt: str) -> str:
    return '{"risk_level": "medium", "insight": "Engagement has dropped.", "reason": "Fewer workouts than last month.", "recommended_action": "Check in with the member."}'


def fake_ai_call_malformed(prompt: str) -> str:
    return "not json at all"


def fake_ai_call_timeout(prompt: str) -> str:
    raise AIProviderError("Simulated timeout.", code="AI_TIMEOUT")


class TestBuildMemberSummary:
    def test_summary_reflects_real_workout_and_attendance_data(self, db_session):
        ctx = setup_stack(db_session, "summary-basic")
        exercise = Exercise(gym_id=ctx["gym"].id, name="Squat")
        db_session.add(exercise)
        db_session.add(WorkoutSession(
            gym_id=ctx["gym"].id, member_id=ctx["member"].id, status=WorkoutSessionStatus.COMPLETED,
        ))
        db_session.commit()

        summary = ai_service.build_member_summary(db_session, gym_id=ctx["gym"].id, member_id=ctx["member"].id)
        assert summary.member_first_name == "Ana"
        assert summary.workouts_last_30_days == 1
        assert summary.membership_status == "ACTIVE"
        assert summary.membership_days_until_expiry == 20

    def test_summary_handles_member_with_no_data(self, db_session):
        ctx = setup_stack(db_session, "summary-empty")
        summary = ai_service.build_member_summary(db_session, gym_id=ctx["gym"].id, member_id=ctx["member"].id)
        assert summary.workouts_last_30_days == 0
        assert summary.weight_trend_kg is None


class TestGenerateInsightForMember:
    def test_valid_ai_response_creates_insight(self, db_session):
        ctx = setup_stack(db_session, "gen-valid")
        insight = ai_service.generate_insight_for_member(
            db_session, gym_id=ctx["gym"].id, member_id=ctx["member"].id, ai_call=fake_ai_call_valid
        )
        assert insight.risk_level.value == "medium"
        assert insight.insight == "Engagement has dropped."

    def test_malformed_ai_response_raises_and_logs_audit(self, db_session):
        from app.ai.service import AIResponseValidationError
        from app.common.models import AuditLog

        ctx = setup_stack(db_session, "gen-malformed")
        with pytest.raises(AIResponseValidationError):
            ai_service.generate_insight_for_member(
                db_session, gym_id=ctx["gym"].id, member_id=ctx["member"].id, ai_call=fake_ai_call_malformed
            )

        failure_logs = db_session.query(AuditLog).filter(AuditLog.action == "AI_INSIGHT_FAILED").all()
        assert len(failure_logs) == 1
        assert failure_logs[0].entity_id == str(ctx["member"].id)

    def test_provider_timeout_raises_and_does_not_create_insight(self, db_session):
        from app.ai.models import AIInsight

        ctx = setup_stack(db_session, "gen-timeout")
        with pytest.raises(AIProviderError):
            ai_service.generate_insight_for_member(
                db_session, gym_id=ctx["gym"].id, member_id=ctx["member"].id, ai_call=fake_ai_call_timeout
            )
        count = db_session.query(AIInsight).filter(AIInsight.member_id == ctx["member"].id).count()
        assert count == 0

    def test_one_member_failure_does_not_affect_another_members_insight(self, db_session):
        """Section 20: a batch process must isolate per-member failures."""
        ctx1 = setup_stack(db_session, "batch-fail")
        ctx2 = setup_stack(db_session, "batch-ok")

        with pytest.raises(Exception):
            ai_service.generate_insight_for_member(
                db_session, gym_id=ctx1["gym"].id, member_id=ctx1["member"].id, ai_call=fake_ai_call_malformed
            )
        # A completely separate call for member 2 must succeed normally.
        insight = ai_service.generate_insight_for_member(
            db_session, gym_id=ctx2["gym"].id, member_id=ctx2["member"].id, ai_call=fake_ai_call_valid
        )
        assert insight is not None


class TestAIInsightAPI:
    def test_owner_can_view_insight_via_api_after_generation(self, client, db_session):
        ctx = setup_stack(db_session, "api-view")
        ai_service.generate_insight_for_member(
            db_session, gym_id=ctx["gym"].id, member_id=ctx["member"].id, ai_call=fake_ai_call_valid
        )
        owner_token = login(client, ctx["owner"].email, "OwnerPass123!")
        resp = client.get(f"/api/v1/ai/insights/members/{ctx['member'].id}", headers=auth_header(owner_token))
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 1

    def test_member_sees_own_insights_only(self, client, db_session):
        ctx = setup_stack(db_session, "api-member-view")
        ai_service.generate_insight_for_member(
            db_session, gym_id=ctx["gym"].id, member_id=ctx["member"].id, ai_call=fake_ai_call_valid
        )
        member_token = login(client, ctx["member_user"].email, "MemberPass123!")
        resp = client.get("/api/v1/ai/insights/me", headers=auth_header(member_token))
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 1

    def test_owner_b_cannot_view_gym_a_member_insights(self, client, db_session):
        ctx_a = setup_stack(db_session, "api-cross-a")
        ctx_b = setup_stack(db_session, "api-cross-b")
        ai_service.generate_insight_for_member(
            db_session, gym_id=ctx_a["gym"].id, member_id=ctx_a["member"].id, ai_call=fake_ai_call_valid
        )
        token_b = login(client, ctx_b["owner"].email, "OwnerPass123!")
        resp = client.get(f"/api/v1/ai/insights/members/{ctx_a['member'].id}", headers=auth_header(token_b))
        assert resp.status_code == 404

    def test_generate_endpoint_surfaces_provider_failure_as_502(self, client, db_session, monkeypatch):
        """The live /generate endpoint uses the REAL call_ai_provider, which
        has no reachable provider configured in this environment — proving
        the failure path surfaces cleanly as a normal API error rather than
        crashing the request."""
        ctx = setup_stack(db_session, "api-real-failure")
        owner_token = login(client, ctx["owner"].email, "OwnerPass123!")
        resp = client.post(
            "/api/v1/ai/insights/generate", json={"member_id": str(ctx["member"].id)}, headers=auth_header(owner_token)
        )
        assert resp.status_code == 502
        assert resp.json()["error"]["code"] in (
            "AI_NOT_CONFIGURED", "AI_REQUEST_FAILED", "AI_TIMEOUT", "AI_PROVIDER_HTTP_ERROR"
        )

    def test_generate_endpoint_rejects_cross_tenant_member(self, client, db_session):
        ctx_a = setup_stack(db_session, "api-gen-cross-a")
        ctx_b = setup_stack(db_session, "api-gen-cross-b")
        token_a = login(client, ctx_a["owner"].email, "OwnerPass123!")
        resp = client.post(
            "/api/v1/ai/insights/generate", json={"member_id": str(ctx_b["member"].id)}, headers=auth_header(token_a)
        )
        assert resp.status_code == 404

    def test_member_cannot_call_generate_endpoint(self, client, db_session):
        ctx = setup_stack(db_session, "api-gen-member-block")
        member_token = login(client, ctx["member_user"].email, "MemberPass123!")
        resp = client.post(
            "/api/v1/ai/insights/generate", json={"member_id": str(ctx["member"].id)}, headers=auth_header(member_token)
        )
        assert resp.status_code == 403
