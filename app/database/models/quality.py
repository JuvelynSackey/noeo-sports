"""Data quality scoring and raw provider record archive.

MASTER BUILD PROMPT sections 14, 15, 10.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base
from app.database.models.enums import DataQualityStatus
from app.database.models.mixins import TimestampMixin, utcnow


class DataQuality(Base, TimestampMixin):
    __tablename__ = "data_quality"

    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"), nullable=False, index=True)
    season_id: Mapped[int | None] = mapped_column(ForeignKey("seasons.id"), index=True)

    overall_score: Mapped[float] = mapped_column(Float, nullable=False)
    status: Mapped[DataQualityStatus] = mapped_column(nullable=False)
    completeness: Mapped[float | None] = mapped_column(Float)
    freshness: Mapped[float | None] = mapped_column(Float)
    source_reliability: Mapped[float | None] = mapped_column(Float)
    team_mapping_quality: Mapped[float | None] = mapped_column(Float)
    fixture_completeness: Mapped[float | None] = mapped_column(Float)
    issues: Mapped[dict | None] = mapped_column(JSON)
    evaluated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ProviderRecord(Base, TimestampMixin):
    """Raw provider payload archive, kept for provenance / dispute resolution."""

    __tablename__ = "provider_records"

    id: Mapped[int] = mapped_column(primary_key=True)
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    record_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_record_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    retrieved_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
