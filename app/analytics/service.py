"""
Analytics service layer.

Section 4's entity list has no dedicated analytics table, so periodic
snapshots are computed on demand and recorded via audit_logs (action=
ANALYTICS_SNAPSHOT) rather than a new persistence layer — a deliberate,
minimal-footprint choice for the prototype. The owner dashboard (Phase 16)
computes its numbers live from the same underlying tables rather than
reading these snapshots, so this module is not a hard dependency of the
dashboard — it exists for the "generate_periodic_analytics" Beat task
required by section 12.
"""
from __future__ import annotations

import uuid
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.enums import MembershipStatus
from app.common.pagination import PageParams
from app.common.responses import PaginatedData
from app.members.models import Member
from app.memberships.models import Membership
from app.workouts.models import WorkoutSession


def compute_gym_snapshot(db: Session, *, gym_id: uuid.UUID) -> dict:
    total_members = db.scalar(select(func.count()).select_from(Member).where(Member.gym_id == gym_id)) or 0

    active_memberships = db.scalar(
        select(func.count()).select_from(Membership).where(
            Membership.gym_id == gym_id, Membership.status == MembershipStatus.ACTIVE
        )
    ) or 0

    restricted_memberships = db.scalar(
        select(func.count()).select_from(Membership).where(
            Membership.gym_id == gym_id, Membership.status == MembershipStatus.RESTRICTED
        )
    ) or 0

    from datetime import datetime, timezone

    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    workouts_last_7_days = db.scalar(
        select(func.count()).select_from(WorkoutSession).where(
            WorkoutSession.gym_id == gym_id, WorkoutSession.started_at >= seven_days_ago
        )
    ) or 0

    return {
        "gym_id": str(gym_id),
        "total_members": total_members,
        "active_memberships": active_memberships,
        "restricted_memberships": restricted_memberships,
        "workouts_last_7_days": workouts_last_7_days,
    }


def get_owner_dashboard_summary(db: Session, *, gym_id: uuid.UUID) -> dict:
    """
    Section 13's dashboard numbers, computed live (not from the periodic
    snapshot) so the owner always sees current data. Pulls from payments'
    finance summary and the AI module's recent-insight count rather than
    duplicating those queries here.
    """
    from app.ai.models import AIInsight
    from app.attendance.models import Attendance
    from app.payments.service import get_finance_summary

    total_members = db.scalar(select(func.count()).select_from(Member).where(Member.gym_id == gym_id)) or 0

    def _count_by_status(status: MembershipStatus) -> int:
        return db.scalar(
            select(func.count()).select_from(Membership).where(Membership.gym_id == gym_id, Membership.status == status)
        ) or 0

    active_members = _count_by_status(MembershipStatus.ACTIVE)
    payment_due_members = _count_by_status(MembershipStatus.PAYMENT_DUE)
    restricted_members = _count_by_status(MembershipStatus.RESTRICTED)

    expiring_within_7_days = db.scalar(
        select(func.count()).select_from(Membership).where(
            Membership.gym_id == gym_id, Membership.status == MembershipStatus.ACTIVE,
            Membership.end_date <= date.today() + timedelta(days=7), Membership.end_date >= date.today(),
        )
    ) or 0

    attendance_today_count = db.scalar(
        select(func.count()).select_from(Attendance).where(Attendance.gym_id == gym_id, Attendance.date == date.today())
    ) or 0

    finance = get_finance_summary(db, gym_id=gym_id)

    thirty_days_ago = date.today() - timedelta(days=30)
    recent_ai_insights_count = db.scalar(
        select(func.count()).select_from(AIInsight).where(
            AIInsight.gym_id == gym_id, AIInsight.created_at >= thirty_days_ago
        )
    ) or 0

    return {
        "total_members": total_members,
        "active_members": active_members,
        "payment_due_members": payment_due_members,
        "restricted_members": restricted_members,
        "expiring_within_7_days": expiring_within_7_days,
        "attendance_today_count": attendance_today_count,
        "total_revenue": finance["total_revenue"],
        "total_expenses": finance["total_expenses"],
        "net_profit": finance["net_profit"],
        "recent_ai_insights_count": recent_ai_insights_count,
    }


def get_dashboard_member_rows(db: Session, *, gym_id: uuid.UUID, params: PageParams) -> PaginatedData:
    """
    Section 13's member list: name, membership ID, status, attendance,
    progress trend. Paginated deliberately (section 41: never load a whole
    gym's member table into memory) — each row does a small, bounded number
    of extra lookups rather than one giant join, which keeps this simple and
    correct at prototype scale while staying easy to optimize later with a
    single batched query if the member list ever gets large.
    """
    from app.attendance.models import Attendance
    from app.common.pagination import paginate
    from app.progress.models import ProgressRecord

    base_stmt = select(Member).where(Member.gym_id == gym_id).order_by(Member.created_at.desc())
    page = paginate(db, base_stmt, params)

    rows = []
    thirty_days_ago = date.today() - timedelta(days=30)
    for member in page.items:
        membership = db.scalar(
            select(Membership)
            .where(Membership.gym_id == gym_id, Membership.member_id == member.id)
            .order_by(Membership.created_at.desc())
            .limit(1)
        )
        attendance_count = db.scalar(
            select(func.count()).select_from(Attendance).where(
                Attendance.gym_id == gym_id, Attendance.member_id == member.id, Attendance.date >= thirty_days_ago
            )
        ) or 0

        progress_rows = list(db.scalars(
            select(ProgressRecord)
            .where(
                ProgressRecord.gym_id == gym_id, ProgressRecord.member_id == member.id,
                ProgressRecord.weight_kg.is_not(None),
            )
            .order_by(ProgressRecord.recorded_at.asc())
        ))
        if len(progress_rows) >= 2:
            delta = float(progress_rows[-1].weight_kg) - float(progress_rows[0].weight_kg)
            trend = "stable" if abs(delta) < 0.5 else ("up" if delta > 0 else "down")
        else:
            trend = "no data"

        rows.append({
            "member_id": member.id,
            "full_name": member.full_name,
            "membership_id_code": membership.membership_id_code if membership else None,
            "membership_status": membership.status.value if membership else None,
            "attendance_percentage_last_30_days": round((attendance_count / 30) * 100, 1),
            "progress_trend": trend,
        })

    page.items = rows
    return page
