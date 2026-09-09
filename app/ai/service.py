"""
AI insight service layer.

Pipeline (section 19):
    PostgreSQL -> build_member_summary -> build_prompt -> [AI provider] ->
    parse_and_validate_ai_response -> AIInsight row

Every step except the actual provider call is pure/DB-only and independently
testable. The provider call itself is injected as a parameter everywhere
(`ai_call`) specifically so tests never need network access or mocking
frameworks — they just pass a fake function.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.client import AIProviderError, call_ai_provider
from app.ai.models import AIInsight
from app.ai.schemas import AIInsightResponse, MemberActivitySummary
from app.attendance.models import Attendance
from app.common.audit import log_audit_event
from app.common.pagination import PageParams, paginate
from app.common.responses import PaginatedData
from app.core.exceptions import AppError
from app.members.models import Member
from app.memberships.service import get_current_membership
from app.progress.models import ProgressRecord
from app.workouts.models import WorkoutSession


class AIResponseValidationError(AppError):
    """The model responded, but the content didn't validate against
    AIInsightResponse — malformed JSON, missing fields, wrong types."""

    code = "AI_INVALID_RESPONSE"

    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message, code=code or self.code, status_code=502)


def build_member_summary(db: Session, *, gym_id: uuid.UUID, member_id: uuid.UUID) -> MemberActivitySummary:
    member = db.get(Member, member_id)
    now = datetime.now(timezone.utc)

    last_30 = now - timedelta(days=30)
    prev_30 = now - timedelta(days=60)

    workouts_last_30_count = len(list(db.scalars(
        select(WorkoutSession.id).where(
            WorkoutSession.gym_id == gym_id, WorkoutSession.member_id == member_id, WorkoutSession.started_at >= last_30
        )
    )))
    workouts_prev_30_count = len(list(db.scalars(
        select(WorkoutSession.id).where(
            WorkoutSession.gym_id == gym_id, WorkoutSession.member_id == member_id,
            WorkoutSession.started_at >= prev_30, WorkoutSession.started_at < last_30,
        )
    )))

    attendance_last_30 = len(list(db.scalars(
        select(Attendance.id).where(
            Attendance.gym_id == gym_id, Attendance.member_id == member_id, Attendance.date >= last_30.date()
        )
    )))
    attendance_pct = round((attendance_last_30 / 30) * 100, 1)

    progress_rows = list(db.scalars(
        select(ProgressRecord)
        .where(
            ProgressRecord.gym_id == gym_id, ProgressRecord.member_id == member_id,
            ProgressRecord.recorded_at >= prev_30, ProgressRecord.weight_kg.is_not(None),
        )
        .order_by(ProgressRecord.recorded_at.asc())
    ))
    weight_trend_kg = None
    if len(progress_rows) >= 2:
        weight_trend_kg = float(progress_rows[-1].weight_kg) - float(progress_rows[0].weight_kg)

    membership = get_current_membership(db, gym_id=gym_id, member_id=member_id)
    membership_status = membership.status.value if membership else "NONE"
    days_until_expiry = (membership.end_date - now.date()).days if membership else None

    return MemberActivitySummary(
        member_first_name=(member.full_name.split(" ")[0] if member else "Member"),
        attendance_percentage_last_30_days=attendance_pct,
        workouts_last_30_days=workouts_last_30_count,
        workouts_previous_30_days=workouts_prev_30_count,
        weight_trend_kg=weight_trend_kg,
        membership_status=membership_status,
        membership_days_until_expiry=days_until_expiry,
    )


def build_prompt(summary: MemberActivitySummary) -> str:
    """
    Deliberately instructs the model to return ONLY JSON matching the exact
    schema — the actual guarantee still comes from parse_and_validate below,
    not from trusting the model to follow instructions.
    """
    return (
        "You are a gym engagement analyst. Given the member activity summary below, "
        "assess churn/engagement risk and respond with ONLY a single JSON object — "
        "no markdown, no code fences, no extra text — with exactly these keys: "
        '"risk_level" (one of "low", "medium", "high"), "insight" (short string), '
        '"reason" (short string explaining the assessment), '
        '"recommended_action" (short string suggesting what the gym owner should do).\n\n'
        f"Member activity summary:\n{summary.model_dump_json(indent=2)}\n"
    )


def parse_and_validate_ai_response(raw_text: str) -> AIInsightResponse:
    """
    Section 37: the model is never trusted. Handles empty responses,
    markdown-fenced JSON, malformed JSON, and missing/invalid fields, each
    with a distinct, inspectable error code.
    """
    if raw_text is None or not raw_text.strip():
        raise AIResponseValidationError("AI provider returned an empty response.", code="AI_EMPTY_RESPONSE")

    text = raw_text.strip()
    if text.startswith("```"):
        # Strip a leading ```json / ``` fence and a trailing ``` if present.
        text = text.split("```", 2)[1] if text.count("```") >= 2 else text.strip("`")
        text = text.removeprefix("json").strip() if text.lower().startswith("json") else text.strip()

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise AIResponseValidationError(f"AI response was not valid JSON: {exc}", code="AI_MALFORMED_JSON") from exc

    if not isinstance(parsed, dict):
        raise AIResponseValidationError("AI response JSON was not an object.", code="AI_MALFORMED_JSON")

    try:
        return AIInsightResponse.model_validate(parsed)
    except Exception as exc:  # pydantic.ValidationError, but caught broadly for a single error path
        raise AIResponseValidationError(f"AI response failed schema validation: {exc}", code="AI_SCHEMA_INVALID") from exc


def generate_insight_for_member(
    db: Session, *, gym_id: uuid.UUID, member_id: uuid.UUID,
    ai_call: Callable[[str], str] = call_ai_provider,
) -> AIInsight:
    """
    Runs the full pipeline for one member. Raises AIProviderError or
    AIResponseValidationError on failure — callers (the Celery task, or a
    manual-trigger endpoint) decide how to handle that per-member so one
    failure never takes down a whole batch (section 20: "AI failure handled
    safely").
    """
    summary = build_member_summary(db, gym_id=gym_id, member_id=member_id)
    prompt = build_prompt(summary)

    try:
        raw_response = ai_call(prompt)
        validated = parse_and_validate_ai_response(raw_response)
    except (AIProviderError, AIResponseValidationError) as exc:
        log_audit_event(
            db, actor_user_id=None, gym_id=gym_id, action="AI_INSIGHT_FAILED",
            entity_type="member", entity_id=str(member_id), metadata={"error_code": exc.code, "error": exc.message},
        )
        db.commit()
        raise

    insight = AIInsight(
        gym_id=gym_id, member_id=member_id, risk_level=validated.risk_level, insight=validated.insight,
        reason=validated.reason, recommended_action=validated.recommended_action,
    )
    db.add(insight)
    db.flush()

    log_audit_event(
        db, actor_user_id=None, gym_id=gym_id, action="AI_INSIGHT_GENERATED",
        entity_type="ai_insight", entity_id=str(insight.id), metadata={"risk_level": validated.risk_level.value},
    )

    from app.common.enums import NotificationType
    from app.notifications.service import notify_gym_owners

    notify_gym_owners(
        db, gym_id=gym_id, member_id=member_id, type=NotificationType.AI_INSIGHT,
        title=f"New AI insight ({validated.risk_level.value} risk)", message=validated.insight,
    )

    db.commit()
    db.refresh(insight)
    return insight


def list_insights_for_member(db: Session, *, gym_id: uuid.UUID, member_id: uuid.UUID, params: PageParams) -> PaginatedData:
    stmt = (
        select(AIInsight)
        .where(AIInsight.gym_id == gym_id, AIInsight.member_id == member_id)
        .order_by(AIInsight.created_at.desc())
    )
    return paginate(db, stmt, params)


def list_insights_for_gym(db: Session, *, gym_id: uuid.UUID, params: PageParams) -> PaginatedData:
    """Owner dashboard feed (section 20): all recent insights across the gym."""
    stmt = select(AIInsight).where(AIInsight.gym_id == gym_id).order_by(AIInsight.created_at.desc())
    return paginate(db, stmt, params)
