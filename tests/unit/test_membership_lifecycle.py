"""
Unit tests for app.memberships.lifecycle (sections 12/35/36).

These test the pure state-machine functions directly — no HTTP, no Celery —
so every boundary case from section 35 can be pinned down exactly.
"""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.common.enums import MembershipStatus
from app.memberships.lifecycle import (
    EXPIRE_AFTER_RESTRICTED_DAYS,
    apply_expiry_check,
    apply_payment_due_check,
    apply_expiry_check as _unused,  # noqa
    is_restricted,
    reactivate_with_payment,
)


class FakeMembership:
    """A lightweight stand-in for the ORM Membership, since these functions
    only touch a handful of attributes and don't need a real DB row."""

    def __init__(self, status, end_date, payment_due_since=None, restricted_at=None):
        self.status = status
        self.end_date = end_date
        self.payment_due_since = payment_due_since
        self.restricted_at = restricted_at


GRACE = 7


class TestActiveToPaymentDue:
    def test_still_within_end_date_stays_active(self):
        m = FakeMembership(MembershipStatus.ACTIVE, end_date=date(2026, 6, 15))
        result = apply_payment_due_check(m, today=date(2026, 6, 15), grace_period_days=GRACE)
        assert result.changed is False
        assert m.status == MembershipStatus.ACTIVE

    def test_day_after_end_date_becomes_payment_due(self):
        m = FakeMembership(MembershipStatus.ACTIVE, end_date=date(2026, 6, 15))
        result = apply_payment_due_check(m, today=date(2026, 6, 16), grace_period_days=GRACE)
        assert result.changed is True
        assert m.status == MembershipStatus.PAYMENT_DUE
        assert m.payment_due_since.date() == date(2026, 6, 15)


class TestGracePeriodBoundary:
    """The exact boundary the spec calls out explicitly (section 35)."""

    def _payment_due_membership(self, due_since: date):
        return FakeMembership(
            MembershipStatus.PAYMENT_DUE,
            end_date=due_since,
            payment_due_since=datetime.combine(due_since, datetime.min.time(), tzinfo=timezone.utc),
        )

    @pytest.mark.parametrize("days_missed", [1, 2, 3, 4, 5, 6, 7])
    def test_within_grace_period_stays_payment_due(self, days_missed):
        due_since = date(2026, 6, 1)
        today = due_since + timedelta(days=days_missed)
        m = self._payment_due_membership(due_since)
        result = apply_payment_due_check(m, today=today, grace_period_days=GRACE)
        assert m.status == MembershipStatus.PAYMENT_DUE, f"day {days_missed} should still be PAYMENT_DUE"
        assert result.changed is False

    def test_exactly_seven_days_is_not_restricted(self):
        due_since = date(2026, 6, 1)
        m = self._payment_due_membership(due_since)
        apply_payment_due_check(m, today=due_since + timedelta(days=7), grace_period_days=GRACE)
        assert m.status == MembershipStatus.PAYMENT_DUE

    def test_eight_days_becomes_restricted(self):
        due_since = date(2026, 6, 1)
        m = self._payment_due_membership(due_since)
        result = apply_payment_due_check(m, today=due_since + timedelta(days=8), grace_period_days=GRACE)
        assert m.status == MembershipStatus.RESTRICTED
        assert result.changed is True
        assert m.restricted_at is not None

    @pytest.mark.parametrize("days_missed", [9, 10, 30, 100])
    def test_beyond_eight_days_stays_restricted_on_repeat_runs(self, days_missed):
        due_since = date(2026, 6, 1)
        m = self._payment_due_membership(due_since)
        apply_payment_due_check(m, today=due_since + timedelta(days=8), grace_period_days=GRACE)
        assert m.status == MembershipStatus.RESTRICTED
        # Running again later (simulating repeated Beat executions) must not
        # error or bounce the status around — it's a terminal-for-this-check state.
        result = apply_payment_due_check(m, today=due_since + timedelta(days=days_missed), grace_period_days=GRACE)
        assert result.changed is False
        assert m.status == MembershipStatus.RESTRICTED


class TestIdempotency:
    """Section 36: running the check twice on the same day must not
    duplicate state changes or corrupt the membership."""

    def test_running_twice_same_day_only_transitions_once(self):
        m = FakeMembership(MembershipStatus.ACTIVE, end_date=date(2026, 6, 1))
        r1 = apply_payment_due_check(m, today=date(2026, 6, 2), grace_period_days=GRACE)
        assert r1.changed is True
        assert m.status == MembershipStatus.PAYMENT_DUE
        due_since_after_first_run = m.payment_due_since

        r2 = apply_payment_due_check(m, today=date(2026, 6, 2), grace_period_days=GRACE)
        assert r2.changed is False
        assert m.payment_due_since == due_since_after_first_run  # untouched


class TestReactivation:
    def test_reactivate_from_payment_due(self):
        m = FakeMembership(
            MembershipStatus.PAYMENT_DUE, end_date=date(2026, 6, 1),
            payment_due_since=datetime(2026, 6, 1, tzinfo=timezone.utc),
        )
        result = reactivate_with_payment(m, plan_duration_days=30, payment_date=date(2026, 6, 5))
        assert result.changed is True
        assert m.status == MembershipStatus.ACTIVE
        assert m.payment_due_since is None
        assert m.restricted_at is None
        assert m.end_date == date(2026, 7, 5)

    def test_reactivate_from_restricted(self):
        m = FakeMembership(
            MembershipStatus.RESTRICTED, end_date=date(2026, 6, 1),
            payment_due_since=datetime(2026, 6, 1, tzinfo=timezone.utc),
            restricted_at=datetime(2026, 6, 9, tzinfo=timezone.utc),
        )
        result = reactivate_with_payment(m, plan_duration_days=30, payment_date=date(2026, 6, 20))
        assert m.status == MembershipStatus.ACTIVE
        assert m.restricted_at is None
        assert m.end_date == date(2026, 7, 20)
        assert result.changed is True

    def test_reactivate_already_active_reports_unchanged_but_still_renews(self):
        """Renewing early (before anything lapsed) should still extend the
        end date, but 'changed' reflects the status transition, not the date."""
        m = FakeMembership(MembershipStatus.ACTIVE, end_date=date(2026, 6, 15))
        result = reactivate_with_payment(m, plan_duration_days=30, payment_date=date(2026, 6, 1))
        assert result.changed is False
        assert m.status == MembershipStatus.ACTIVE
        assert m.end_date == date(2026, 7, 1)


class TestExpiryCheck:
    def test_restricted_under_threshold_not_expired(self):
        m = FakeMembership(
            MembershipStatus.RESTRICTED, end_date=date(2026, 1, 1),
            restricted_at=datetime(2026, 1, 10, tzinfo=timezone.utc),
        )
        result = apply_expiry_check(m, today=date(2026, 1, 10) + timedelta(days=EXPIRE_AFTER_RESTRICTED_DAYS))
        assert result.changed is False
        assert m.status == MembershipStatus.RESTRICTED

    def test_restricted_beyond_threshold_expires(self):
        restricted_since = date(2026, 1, 10)
        m = FakeMembership(
            MembershipStatus.RESTRICTED, end_date=date(2026, 1, 1),
            restricted_at=datetime.combine(restricted_since, datetime.min.time(), tzinfo=timezone.utc),
        )
        result = apply_expiry_check(m, today=restricted_since + timedelta(days=EXPIRE_AFTER_RESTRICTED_DAYS + 1))
        assert result.changed is True
        assert m.status == MembershipStatus.EXPIRED

    def test_active_membership_untouched_by_expiry_check(self):
        m = FakeMembership(MembershipStatus.ACTIVE, end_date=date(2026, 1, 1))
        result = apply_expiry_check(m, today=date(2026, 12, 1))
        assert result.changed is False
        assert m.status == MembershipStatus.ACTIVE


class TestIsRestricted:
    def test_true_only_for_restricted_status(self):
        assert is_restricted(FakeMembership(MembershipStatus.RESTRICTED, end_date=date.today())) is True
        for status in (MembershipStatus.ACTIVE, MembershipStatus.PAYMENT_DUE, MembershipStatus.EXPIRED, MembershipStatus.CANCELLED):
            assert is_restricted(FakeMembership(status, end_date=date.today())) is False


class TestBlocksNewTracking:
    def test_restricted_blocks(self):
        from app.memberships.lifecycle import blocks_new_tracking
        assert blocks_new_tracking(FakeMembership(MembershipStatus.RESTRICTED, end_date=date.today())) is True

    def test_expired_also_blocks(self):
        from app.memberships.lifecycle import blocks_new_tracking
        assert blocks_new_tracking(FakeMembership(MembershipStatus.EXPIRED, end_date=date.today())) is True

    def test_cancelled_also_blocks(self):
        from app.memberships.lifecycle import blocks_new_tracking
        assert blocks_new_tracking(FakeMembership(MembershipStatus.CANCELLED, end_date=date.today())) is True

    def test_active_does_not_block(self):
        from app.memberships.lifecycle import blocks_new_tracking
        assert blocks_new_tracking(FakeMembership(MembershipStatus.ACTIVE, end_date=date.today())) is False

    def test_payment_due_does_not_block(self):
        from app.memberships.lifecycle import blocks_new_tracking
        assert blocks_new_tracking(FakeMembership(MembershipStatus.PAYMENT_DUE, end_date=date.today())) is False
