"""Users (RBAC) and audit logging — MASTER BUILD PROMPT sections 54, 60."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.models.enums import UserRole
from app.database.models.mixins import TimestampMixin, utcnow


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(default=UserRole.VIEWER, nullable=False)
    is_active: Mapped[bool] = mapped_column(default=True, nullable=False)


class AuditLog(Base, TimestampMixin):
    """Every sensitive administrative action — section 54."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    actor_email: Mapped[str | None] = mapped_column(String(255), index=True)
    actor_role: Mapped[str | None] = mapped_column(String(32))
    action: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    resource_type: Mapped[str | None] = mapped_column(String(64))
    resource_id: Mapped[str | None] = mapped_column(String(128))
    details: Mapped[dict | None] = mapped_column(JSON)
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
