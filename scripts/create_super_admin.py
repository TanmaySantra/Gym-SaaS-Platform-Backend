"""
Seed the first SUPER_ADMIN user.

There is deliberately no public /auth/register endpoint: SUPER_ADMIN creates
gyms/owners, owners create members (section 6/24). This script is the one
bootstrap exception, meant to be run once against a fresh database.

Usage:
    python -m scripts.create_super_admin admin@gym-saas.com "Platform Admin" "SomeStrongPassword123!"
"""
from __future__ import annotations

import sys

import app.models_registry  # noqa: F401  (registers all ORM relationships before first query)
from app.core.database import SessionLocal
from app.core.security import hash_password
from app.common.enums import UserRole
from app.users.models import User


def create_super_admin(email: str, full_name: str, password: str) -> None:
    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.email == email.lower()).one_or_none()
        if existing is not None:
            print(f"User with email {email} already exists (role={existing.role.value}). Aborting.")
            return

        admin = User(
            email=email.lower(),
            full_name=full_name,
            hashed_password=hash_password(password),
            role=UserRole.SUPER_ADMIN,
            gym_id=None,
            is_active=True,
        )
        db.add(admin)
        db.commit()
        print(f"Created SUPER_ADMIN: {email}")
    finally:
        db.close()


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("Usage: python -m scripts.create_super_admin <email> <full_name> <password>")
        sys.exit(1)
    create_super_admin(sys.argv[1], sys.argv[2], sys.argv[3])
