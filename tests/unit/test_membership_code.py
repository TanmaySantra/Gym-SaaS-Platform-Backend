"""Unit tests for app.memberships.utils (section 32)."""
import re

from app.memberships.utils import _gym_prefix, generate_unique_membership_code


class TestGymPrefix:
    def test_strips_non_alnum_and_uppercases(self):
        assert _gym_prefix("iron-paradise") == "IRONPA"

    def test_pads_short_slugs(self):
        assert _gym_prefix("ab") == "AB0"

    def test_truncates_long_slugs_to_six_chars(self):
        assert len(_gym_prefix("a-very-long-gym-slug-name")) == 6


class TestGenerateUniqueMembershipCode:
    def test_format_matches_pattern(self, db_session):
        code = generate_unique_membership_code(db_session, gym_slug="iron-paradise")
        assert re.match(r"^[A-Z0-9]+-[A-Z0-9]{5}$", code)

    def test_excludes_ambiguous_characters(self, db_session):
        codes = {generate_unique_membership_code(db_session, gym_slug="test") for _ in range(50)}
        suffixes = "".join(c.split("-")[1] for c in codes)
        for ambiguous in "01OI":
            assert ambiguous not in suffixes

    def test_generates_distinct_codes(self, db_session):
        codes = {generate_unique_membership_code(db_session, gym_slug="test") for _ in range(100)}
        assert len(codes) == 100

    def test_does_not_collide_with_existing_membership(self, db_session):
        """If a membership with a given code already exists, the generator
        must never return that same code again."""
        from datetime import date

        from app.common.enums import GymStatus, MembershipStatus
        from app.gyms.models import Gym
        from app.members.models import Member
        from app.memberships.models import Membership, MembershipPlan

        gym = Gym(name="Test", slug="testgym", status=GymStatus.ACTIVE)
        db_session.add(gym)
        db_session.flush()
        member = Member(gym_id=gym.id, full_name="X")
        plan = MembershipPlan(gym_id=gym.id, name="Monthly", duration_days=30, price=50)
        db_session.add_all([member, plan])
        db_session.flush()

        existing_code = generate_unique_membership_code(db_session, gym_slug=gym.slug)
        membership = Membership(
            gym_id=gym.id, member_id=member.id, plan_id=plan.id, membership_id_code=existing_code,
            status=MembershipStatus.ACTIVE, start_date=date.today(), end_date=date.today(),
        )
        db_session.add(membership)
        db_session.commit()

        for _ in range(20):
            assert generate_unique_membership_code(db_session, gym_slug=gym.slug) != existing_code
