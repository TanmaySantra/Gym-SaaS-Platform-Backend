"""Workout endpoints (sections 14/15/25). Mounted at /api/v1/workouts."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.dependencies import AuthContext, get_current_member, require_roles
from app.common.enums import UserRole
from app.common.pagination import PageParams, pagination_params
from app.common.responses import PaginatedData, PaginatedResponse, SuccessResponse
from app.core.database import get_db
from app.members.models import Member
from app.workouts import service
from app.workouts.schemas import (
    ExerciseCreate,
    ExerciseLogCreate,
    ExerciseLogOut,
    ExerciseOut,
    WorkoutSessionCreate,
    WorkoutSessionOut,
)

router = APIRouter()


@router.post(
    "/exercises", response_model=SuccessResponse[ExerciseOut], status_code=201,
    dependencies=[Depends(require_roles(UserRole.OWNER))],
)
def create_exercise(
    payload: ExerciseCreate, ctx: AuthContext = Depends(require_roles(UserRole.OWNER)), db: Session = Depends(get_db)
):
    exercise = service.create_exercise(
        db, actor_id=ctx.user.id, gym_id=ctx.gym_id, name=payload.name, muscle_group=payload.muscle_group
    )
    return SuccessResponse(data=ExerciseOut.model_validate(exercise))


@router.get(
    "/exercises", response_model=PaginatedResponse[ExerciseOut],
    dependencies=[Depends(require_roles(UserRole.OWNER, UserRole.MEMBER))],
)
def list_exercises(
    params: PageParams = Depends(pagination_params),
    ctx: AuthContext = Depends(require_roles(UserRole.OWNER, UserRole.MEMBER)),
    db: Session = Depends(get_db),
):
    data = service.list_exercises(db, gym_id=ctx.gym_id, params=params)
    return PaginatedResponse(
        data=PaginatedData(
            items=[ExerciseOut.model_validate(e) for e in data.items],
            total=data.total, page=data.page, page_size=data.page_size, total_pages=data.total_pages,
        )
    )


@router.post("/sessions", response_model=SuccessResponse[WorkoutSessionOut], status_code=201)
def start_session(
    payload: WorkoutSessionCreate, member: Member = Depends(get_current_member), db: Session = Depends(get_db)
):
    session = service.start_workout_session(
        db, gym_id=member.gym_id, member_id=member.id, workout_plan_id=payload.workout_plan_id
    )
    return SuccessResponse(data=WorkoutSessionOut.model_validate(session))


@router.get("/sessions", response_model=PaginatedResponse[WorkoutSessionOut])
def list_sessions(
    params: PageParams = Depends(pagination_params), member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    data = service.list_sessions_for_member(db, gym_id=member.gym_id, member_id=member.id, params=params)
    return PaginatedResponse(
        data=PaginatedData(
            items=[WorkoutSessionOut.model_validate(s) for s in data.items],
            total=data.total, page=data.page, page_size=data.page_size, total_pages=data.total_pages,
        )
    )


@router.get("/sessions/{session_id}", response_model=SuccessResponse[WorkoutSessionOut])
def get_session(
    session_id: uuid.UUID, member: Member = Depends(get_current_member), db: Session = Depends(get_db)
):
    session = service.get_session_for_member(db, gym_id=member.gym_id, member_id=member.id, session_id=session_id)
    return SuccessResponse(data=WorkoutSessionOut.model_validate(session))


@router.post("/sessions/{session_id}/logs", response_model=SuccessResponse[ExerciseLogOut], status_code=201)
def add_log(
    session_id: uuid.UUID, payload: ExerciseLogCreate, member: Member = Depends(get_current_member),
    db: Session = Depends(get_db),
):
    log = service.add_exercise_log(
        db, gym_id=member.gym_id, member_id=member.id, session_id=session_id, exercise_id=payload.exercise_id,
        set_number=payload.set_number, reps=payload.reps, weight_kg=payload.weight_kg, notes=payload.notes,
    )
    return SuccessResponse(data=ExerciseLogOut.model_validate(log))


@router.post("/sessions/{session_id}/complete", response_model=SuccessResponse[WorkoutSessionOut])
def complete_session(
    session_id: uuid.UUID, member: Member = Depends(get_current_member), db: Session = Depends(get_db)
):
    session = service.complete_workout_session(db, gym_id=member.gym_id, member_id=member.id, session_id=session_id)
    return SuccessResponse(data=WorkoutSessionOut.model_validate(session))
