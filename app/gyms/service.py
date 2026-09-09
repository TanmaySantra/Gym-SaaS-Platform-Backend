"""
Owner-facing gym service. Deliberately tiny: an OWNER can only ever look up
their OWN gym, using the gym_id resolved by require_tenant_gym_id — there is
no "get gym by id" path here that would accept a client-supplied id.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.core.exceptions import NotFoundError
from app.gyms.models import Gym


def get_own_gym(db: Session, *, gym_id: uuid.UUID) -> Gym:
    gym = db.get(Gym, gym_id)
    if gym is None:
        # Should be unreachable (FK integrity guarantees the gym exists),
        # but fail closed with a generic not-found rather than a 500.
        raise NotFoundError("Gym not found.", code="GYM_NOT_FOUND")
    return gym
