"""Integration tests for the notification system (section 21) — both the
generation hooks (membership lifecycle, AI insights) and the API."""
from datetime import date, timedelta, datetime, timezone

from app.ai import service as ai_service
from app.common.enums import GymStatus, MembershipStatus, NotificationType, UserRole
from app.core.security import hash_password
from app.gyms.models import Gym
from app.members.models import Member
from app.memberships import service as membership_service
from app.memberships.models import Membership, MembershipPlan
from app.notifications.models import Notification
from app.users.models import User


def login(client, email, password):
    resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


def auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def setup_linked_member(db_session, slug):
    gym = Gym(name="Notif Gym", slug=slug, status=GymStatus.ACTIVE)
    db_session.add(gym)
    db_session.flush()
    owner = User(
        email=f"owner-{slug}@test.com", full_name="Owner", hashed_password=hash_password("OwnerPass123!"),
        role=UserRole.OWNER, gym_id=gym.id,
    )
    member = Member(gym_id=gym.id, full_name="Notified Member")
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
    db_session.commit()
    for obj in (gym, owner, member, member_user, plan):
        db_session.refresh(obj)
    return {"gym": gym, "owner": owner, "member": member, "member_user": member_user, "plan": plan}


def make_membership(db_session, gym_id, member_id, plan_id, code, status, end_date, start_date=None):
    m = Membership(
        gym_id=gym_id, member_id=member_id, plan_id=plan_id, membership_id_code=code,
        status=status, start_date=start_date or (end_date - timedelta(days=27)), end_date=end_date,
    )
    db_session.add(m)
    db_session.commit()
    db_session.refresh(m)
    return m


class TestPaymentOverdueNotification:
    def test_active_to_payment_due_notifies_member(self, db_session):
        ctx = setup_linked_member(db_session, "notif-overdue")
        make_membership(
            db_session, ctx["gym"].id, ctx["member"].id, ctx["plan"].id, "NOT1-00001", MembershipStatus.ACTIVE,
            date.today() - timedelta(days=1),
        )
        membership_service.run_membership_checks(db_session, gym_id=ctx["gym"].id)

        notifications = db_session.query(Notification).filter(
            Notification.user_id == ctx["member_user"].id, Notification.type == NotificationType.PAYMENT_OVERDUE
        ).all()
        assert len(notifications) == 1
        assert notifications[0].read is False

    def test_unlinked_member_gets_no_notification_but_no_crash(self, db_session):
        gym = Gym(name="Unlinked Gym", slug="notif-unlinked", status=GymStatus.ACTIVE)
        db_session.add(gym)
        db_session.flush()
        member = Member(gym_id=gym.id, full_name="Unlinked")
        plan = MembershipPlan(gym_id=gym.id, name="Monthly", duration_days=30, price=50)
        db_session.add_all([member, plan])
        db_session.flush()
        make_membership(db_session, gym.id, member.id, plan.id, "NOT2-00001", MembershipStatus.ACTIVE, date.today() - timedelta(days=1))

        result = membership_service.run_membership_checks(db_session, gym_id=gym.id)
        assert result["marked_payment_due"] == 1
        assert result["notifications_sent"] == 0


class TestRestrictionNotification:
    def test_payment_due_to_restricted_notifies_member(self, db_session):
        ctx = setup_linked_member(db_session, "notif-restrict")
        due_date = date.today() - timedelta(days=8)
        m = make_membership(
            db_session, ctx["gym"].id, ctx["member"].id, ctx["plan"].id, "NOT3-00001", MembershipStatus.PAYMENT_DUE,
            due_date,
        )
        m.payment_due_since = datetime.combine(due_date, datetime.min.time(), tzinfo=timezone.utc)
        db_session.commit()

        membership_service.run_membership_checks(db_session, gym_id=ctx["gym"].id)

        notifications = db_session.query(Notification).filter(
            Notification.user_id == ctx["member_user"].id, Notification.type == NotificationType.MEMBERSHIP_RESTRICTED
        ).all()
        assert len(notifications) == 1


class TestExpiringSoonNotification:
    def test_membership_expiring_within_3_days_notifies_member(self, db_session):
        ctx = setup_linked_member(db_session, "notif-expiring")
        make_membership(
            db_session, ctx["gym"].id, ctx["member"].id, ctx["plan"].id, "NOT4-00001", MembershipStatus.ACTIVE,
            date.today() + timedelta(days=2),
        )
        membership_service.run_membership_checks(db_session, gym_id=ctx["gym"].id)

        notifications = db_session.query(Notification).filter(
            Notification.user_id == ctx["member_user"].id, Notification.type == NotificationType.MEMBERSHIP_EXPIRING
        ).all()
        assert len(notifications) == 1

    def test_expiring_notification_not_duplicated_on_repeat_runs(self, db_session):
        ctx = setup_linked_member(db_session, "notif-expiring-dedup")
        make_membership(
            db_session, ctx["gym"].id, ctx["member"].id, ctx["plan"].id, "NOT5-00001", MembershipStatus.ACTIVE,
            date.today() + timedelta(days=2),
        )
        membership_service.run_membership_checks(db_session, gym_id=ctx["gym"].id)
        membership_service.run_membership_checks(db_session, gym_id=ctx["gym"].id)

        notifications = db_session.query(Notification).filter(
            Notification.user_id == ctx["member_user"].id, Notification.type == NotificationType.MEMBERSHIP_EXPIRING
        ).all()
        assert len(notifications) == 1

    def test_membership_far_from_expiry_gets_no_notification(self, db_session):
        ctx = setup_linked_member(db_session, "notif-not-expiring")
        make_membership(
            db_session, ctx["gym"].id, ctx["member"].id, ctx["plan"].id, "NOT6-00001", MembershipStatus.ACTIVE,
            date.today() + timedelta(days=20),
        )
        membership_service.run_membership_checks(db_session, gym_id=ctx["gym"].id)
        notifications = db_session.query(Notification).filter(
            Notification.type == NotificationType.MEMBERSHIP_EXPIRING
        ).all()
        assert len(notifications) == 0


class TestAIInsightNotification:
    def test_generating_insight_notifies_the_owner(self, db_session):
        ctx = setup_linked_member(db_session, "notif-ai")

        def fake_ai_call(prompt):
            return '{"risk_level": "high", "insight": "At risk of churning.", "reason": "No recent visits.", "recommended_action": "Call them."}'

        ai_service.generate_insight_for_member(
            db_session, gym_id=ctx["gym"].id, member_id=ctx["member"].id, ai_call=fake_ai_call
        )

        notifications = db_session.query(Notification).filter(
            Notification.user_id == ctx["owner"].id, Notification.type == NotificationType.AI_INSIGHT
        ).all()
        assert len(notifications) == 1
        assert "At risk of churning." in notifications[0].message


class TestNotificationsAPI:
    def test_member_sees_their_own_notifications(self, client, db_session):
        ctx = setup_linked_member(db_session, "notif-api-member")
        make_membership(
            db_session, ctx["gym"].id, ctx["member"].id, ctx["plan"].id, "NOT7-00001", MembershipStatus.ACTIVE,
            date.today() - timedelta(days=1),
        )
        membership_service.run_membership_checks(db_session, gym_id=ctx["gym"].id)

        token = login(client, ctx["member_user"].email, "MemberPass123!")
        resp = client.get("/api/v1/notifications", headers=auth_header(token))
        assert resp.status_code == 200
        assert resp.json()["data"]["total"] == 1

    def test_mark_as_read(self, client, db_session):
        ctx = setup_linked_member(db_session, "notif-api-read")
        make_membership(
            db_session, ctx["gym"].id, ctx["member"].id, ctx["plan"].id, "NOT8-00001", MembershipStatus.ACTIVE,
            date.today() - timedelta(days=1),
        )
        membership_service.run_membership_checks(db_session, gym_id=ctx["gym"].id)

        token = login(client, ctx["member_user"].email, "MemberPass123!")
        list_resp = client.get("/api/v1/notifications", headers=auth_header(token))
        notif_id = list_resp.json()["data"]["items"][0]["id"]

        read_resp = client.post(f"/api/v1/notifications/{notif_id}/read", headers=auth_header(token))
        assert read_resp.status_code == 200
        assert read_resp.json()["data"]["read"] is True

        unread_resp = client.get("/api/v1/notifications?unread_only=true", headers=auth_header(token))
        assert unread_resp.json()["data"]["total"] == 0

    def test_member_a_cannot_see_member_b_notifications(self, client, db_session):
        ctx_a = setup_linked_member(db_session, "notif-cross-a")
        ctx_b = setup_linked_member(db_session, "notif-cross-b")
        make_membership(
            db_session, ctx_a["gym"].id, ctx_a["member"].id, ctx_a["plan"].id, "NOT9-00001", MembershipStatus.ACTIVE,
            date.today() - timedelta(days=1),
        )
        membership_service.run_membership_checks(db_session, gym_id=ctx_a["gym"].id)

        token_b = login(client, ctx_b["member_user"].email, "MemberPass123!")
        resp = client.get("/api/v1/notifications", headers=auth_header(token_b))
        assert resp.json()["data"]["total"] == 0
