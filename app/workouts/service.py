"""
Workouts service layer (section 15). Every write that creates NEW tracking
data (a session, an exercise log) calls assert_not_restricted first — this is
the section 10 requirement implemented at the one place it actually matters:
the backend, not the mobile UI.
"""
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.audit import log_audit_event
from app.common.enums import WorkoutSessionStatus
from app.common.pagination import PageParams, paginate
from app.common.responses import PaginatedData
from app.core.exceptions import ConflictError, NotFoundError
from app.memberships.service import assert_not_restricted
from app.workouts.models import Exercise, ExerciseLog, WorkoutSession


def create_exercise(db: Session, *, actor_id: uuid.UUID, gym_id: uuid.UUID, name: str, muscle_group: str | None) -> Exercise:
    exercise = Exercise(gym_id=gym_id, name=name, muscle_group=muscle_group)
    db.add(exercise)
    db.flush()
    log_audit_event(
        db, actor_user_id=actor_id, gym_id=gym_id, action="EXERCISE_CREATED",
        entity_type="exercise", entity_id=str(exercise.id), metadata={"name": name},
    )
    db.commit()
    db.refresh(exercise)
    return exercise


def list_exercises(db: Session, *, gym_id: uuid.UUID, params: PageParams) -> PaginatedData:
    stmt = select(Exercise).where(Exercise.gym_id == gym_id).order_by(Exercise.name)
    return paginate(db, stmt, params)


def start_workout_session(
    db: Session, *, gym_id: uuid.UUID, member_id: uuid.UUID, workout_plan_id: uuid.UUID | None
) -> WorkoutSession:
    assert_not_restricted(db, gym_id=gym_id, member_id=member_id)

    session = WorkoutSession(
        gym_id=gym_id, member_id=member_id, workout_plan_id=workout_plan_id, status=WorkoutSessionStatus.IN_PROGRESS
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


def _get_own_session(db: Session, *, gym_id: uuid.UUID, member_id: uuid.UUID, session_id: uuid.UUID) -> WorkoutSession:
    session = db.scalar(
        select(WorkoutSession).where(
            WorkoutSession.id == session_id, WorkoutSession.gym_id == gym_id, WorkoutSession.member_id == member_id
        )
    )
    if session is None:
        raise NotFoundError("Workout session not found.", code="WORKOUT_SESSION_NOT_FOUND")
    return session


def add_exercise_log(
    db: Session, *, gym_id: uuid.UUID, member_id: uuid.UUID, session_id: uuid.UUID, exercise_id: uuid.UUID,
    set_number: int, reps: int, weight_kg, notes: str | None,
) -> ExerciseLog:
    assert_not_restricted(db, gym_id=gym_id, member_id=member_id)

    session = _get_own_session(db, gym_id=gym_id, member_id=member_id, session_id=session_id)
    if session.status != WorkoutSessionStatus.IN_PROGRESS:
        raise ConflictError("Cannot log sets on a session that isn't in progress.", code="SESSION_NOT_IN_PROGRESS")

    exercise = db.scalar(select(Exercise).where(Exercise.id == exercise_id, Exercise.gym_id == gym_id))
    if exercise is None:
        raise NotFoundError("Exercise not found.", code="EXERCISE_NOT_FOUND")

    log = ExerciseLog(
        workout_session_id=session.id, exercise_id=exercise.id, set_number=set_number, reps=reps,
        weight_kg=weight_kg, notes=notes,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return log


def complete_workout_session(db: Session, *, gym_id: uuid.UUID, member_id: uuid.UUID, session_id: uuid.UUID) -> WorkoutSession:
    """
    Completing an in-progress session is NOT blocked by restriction — section
    10 only prohibits creating NEW tracking data; finishing something already
    started is not "new" data and shouldn't strand a member mid-workout the
    moment their membership lapses.
    """
    from datetime import datetime, timezone

    session = _get_own_session(db, gym_id=gym_id, member_id=member_id, session_id=session_id)
    if session.status != WorkoutSessionStatus.IN_PROGRESS:
        raise ConflictError("Session is not in progress.", code="SESSION_NOT_IN_PROGRESS")

    session.status = WorkoutSessionStatus.COMPLETED
    session.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(session)
    return session


def list_sessions_for_member(db: Session, *, gym_id: uuid.UUID, member_id: uuid.UUID, params: PageParams) -> PaginatedData:
    stmt = (
        select(WorkoutSession)
        .where(WorkoutSession.gym_id == gym_id, WorkoutSession.member_id == member_id)
        .order_by(WorkoutSession.started_at.desc())
    )
    return paginate(db, stmt, params)


def get_session_for_member(db: Session, *, gym_id: uuid.UUID, member_id: uuid.UUID, session_id: uuid.UUID) -> WorkoutSession:
    return _get_own_session(db, gym_id=gym_id, member_id=member_id, session_id=session_id)
