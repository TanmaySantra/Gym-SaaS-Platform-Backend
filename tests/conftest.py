"""
Shared pytest fixtures.

Uses a real Postgres database (section 33/38 assume real relational behavior
— FKs, constraints, transactions — which SQLite does not faithfully emulate).
Each test function gets a clean schema via truncation, not a fresh DB, to
keep the suite fast.
"""
from __future__ import annotations

import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://gym_user:gym_password@localhost:5432/gym_saas_test"
)

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import app.models_registry as registry
from app.core.config import settings
from app.core.security import hash_password
from app.common.enums import UserRole


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(settings.DATABASE_URL, future=True)
    registry.Base.metadata.drop_all(eng)
    registry.Base.metadata.create_all(eng)
    yield eng
    eng.dispose()


@pytest.fixture()
def db_session(engine):
    TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    session = TestingSessionLocal()
    yield session
    session.close()
    # Truncate everything between tests so each test starts from a clean slate
    # without paying for a full schema rebuild.
    with engine.begin() as conn:
        table_names = ", ".join(f'"{t.name}"' for t in reversed(registry.Base.metadata.sorted_tables))
        conn.execute(text(f"TRUNCATE {table_names} RESTART IDENTITY CASCADE"))


@pytest.fixture()
def client(engine, monkeypatch):
    from app.core.database import SessionLocal as RealSessionLocal
    from sqlalchemy.orm import sessionmaker as sm

    TestingSessionLocal = sm(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    from app.main import app
    from app.core.database import get_db

    def _override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def super_admin(db_session):
    from app.users.models import User

    user = User(
        email="admin@test.com",
        full_name="Test Admin",
        hashed_password=hash_password("AdminPass123!"),
        role=UserRole.SUPER_ADMIN,
        gym_id=None,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user
