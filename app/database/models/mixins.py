"""Reusable column mixins."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import DateTime
from sqlalchemy.orm import Mapped, mapped_column


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class ProvenanceMixin:
    """MASTER BUILD PROMPT section 10 — every ingested record must be traceable."""

    source_provider: Mapped[str] = mapped_column(nullable=False)
    source_record_id: Mapped[str] = mapped_column(nullable=False)
    retrieved_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )
    data_version: Mapped[str] = mapped_column(default="1", nullable=False)
    validation_status: Mapped[str] = mapped_column(default="PENDING", nullable=False)
