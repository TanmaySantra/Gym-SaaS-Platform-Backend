"""Human-shareable membership ID generation. Never used as a password/secret
on its own — it identifies which membership to link, the member still
chooses their own password at link time."""
from __future__ import annotations

import secrets

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.memberships.models import Membership

# Excludes 0/O and 1/I to avoid ambiguity when read aloud or handwritten.
_SAFE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
_SUFFIX_LENGTH = 5
_MAX_ATTEMPTS = 10


def _gym_prefix(slug: str) -> str:
    alnum = "".join(ch for ch in slug.upper() if ch.isalnum())
    return (alnum[:6] or "GYM").ljust(3, "0")


def generate_unique_membership_code(db: Session, *, gym_slug: str) -> str:
    prefix = _gym_prefix(gym_slug)
    for _ in range(_MAX_ATTEMPTS):
        suffix = "".join(secrets.choice(_SAFE_ALPHABET) for _ in range(_SUFFIX_LENGTH))
        code = f"{prefix}-{suffix}"
        exists = db.scalar(select(Membership.id).where(Membership.membership_id_code == code))
        if exists is None:
            return code
    # Astronomically unlikely with a 32^5 keyspace per gym, but fail loudly
    # rather than silently returning a colliding code.
    raise RuntimeError("Could not generate a unique membership ID after multiple attempts.")
