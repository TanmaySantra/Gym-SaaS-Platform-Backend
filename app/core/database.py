"""
Database engine / session setup (SQLAlchemy 2.x style).

Every ORM model in the codebase inherits from `Base` defined here.
`get_db` is the FastAPI dependency used by all routers/services to obtain
a request-scoped session.
"""
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""
    pass


# pool_pre_ping avoids stale-connection errors against managed Postgres (e.g. Neon).
engine = create_engine(
    settings.DATABASE_URL,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    future=True,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency: yields a session and guarantees it is closed."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def task_session():
    """
    Session context manager for Celery tasks, which have no FastAPI request
    lifecycle to hang a Depends(get_db) off of. Usage:
        with task_session() as db:
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
