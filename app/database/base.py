"""SQLAlchemy engine/session wiring.

Works against SQLite (local/lightweight deployment) or PostgreSQL
(production) purely by swapping DATABASE_URL — see MASTER BUILD PROMPT
section 52.
"""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Shared declarative base for all ORM models."""


def _make_engine():
    settings = get_settings()
    connect_args = {}
    if settings.database_url.startswith("sqlite"):
        connect_args = {"check_same_thread": False}
    return create_engine(settings.database_url, connect_args=connect_args, future=True)


engine = _make_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency / general-purpose session context."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
