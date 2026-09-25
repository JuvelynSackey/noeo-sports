"""Drift/OOD monitoring results and system events.

MASTER BUILD PROMPT sections 40, 41, 42, 51 (sync report), 53 (system monitoring).
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.models.mixins import TimestampMixin, utcnow


class ModelMonitoring(Base, TimestampMixin):
    __tablename__ = "model_monitoring"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"), nullable=False, index=True)
    competition_id: Mapped[int | None] = mapped_column(ForeignKey("competitions.id"), index=True)
    metric_name: Mapped[str] = mapped_column(String(64), nullable=False)
    metric_value: Mapped[float] = mapped_column(Float, nullable=False)
    threshold: Mapped[float | None] = mapped_column(Float)
    breached: Mapped[bool] = mapped_column(default=False, nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSON)
    evaluated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class SystemEvent(Base, TimestampMixin):
    """Sync runs, provider failures, retraining triggers, etc."""

    __tablename__ = "system_events"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(String(16), default="INFO", nullable=False)
    message: Mapped[str] = mapped_column(String(2000), nullable=False)
    context: Mapped[dict | None] = mapped_column(JSON)
    occurred_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
