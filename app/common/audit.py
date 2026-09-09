"""
Thin helper for writing to audit_logs. Kept separate from any one module so
auth, members, memberships, payments, and admin actions can all call the same
function without importing each other.
"""
from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from app.common.models import AuditLog


def log_audit_event(
    db: Session,
    *,
    actor_user_id: uuid.UUID | None,
    gym_id: uuid.UUID | None,
    action: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    metadata: dict | None = None,
) -> AuditLog:
    """
    Writes one audit_logs row. Does NOT commit — caller controls the
    transaction boundary so this can be included atomically with the action
    it's recording (e.g. member creation + its audit row in one commit).
    """
    entry = AuditLog(
        actor_user_id=actor_user_id,
        gym_id=gym_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        metadata_json=metadata,
    )
    db.add(entry)
    return entry
