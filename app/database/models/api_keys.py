"""API keys for programmatic access (MASTER BUILD PROMPT section 24's
"API Management") — a long-lived alternative to the short-lived JWT a
human login issues, for non-interactive/automated callers. A key acts on
behalf of the user who created it, with that user's own (current, not
snapshotted) role; deactivating the owning account disables every key
tied to it too, via the same `User.is_active` check `get_current_user`
already applies to a JWT.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.models.mixins import TimestampMixin


class ApiKey(Base, TimestampMixin):
    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(primary_key=True)
    # The public, non-secret half of the key (looked up directly); the
    # secret half is never stored, only its bcrypt hash — same discipline
    # as a user's password.
    key_id: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    hashed_secret: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    request_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
