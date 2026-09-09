"""Owner-facing gym endpoints. Mounted at /api/v1/gyms."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.common.dependencies import require_tenant_gym_id
from app.common.responses import SuccessResponse
from app.core.database import get_db
from app.gyms import service
from app.gyms.schemas import GymOut

router = APIRouter()


@router.get("/me", response_model=SuccessResponse[GymOut])
def get_my_gym(gym_id=Depends(require_tenant_gym_id), db: Session = Depends(get_db)):
    """
    Returns the CALLER's own gym. gym_id here is derived from the
    authenticated session (require_tenant_gym_id) — an OWNER or MEMBER can
    never pass a different gym's id and see its data through this endpoint.
    """
    gym = service.get_own_gym(db, gym_id=gym_id)
    return SuccessResponse(data=GymOut.model_validate(gym))
