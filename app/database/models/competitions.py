"""Competitions and seasons — MASTER BUILD PROMPT sections 3 and 4."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.models.enums import (
    CompetitionFormat,
    CompetitionStatus,
    CompetitionType,
    DataQualityStatus,
    SeasonStatus,
)
from app.database.models.mixins import ProvenanceMixin, TimestampMixin


class Competition(Base, TimestampMixin, ProvenanceMixin):
    __tablename__ = "competitions"
    __table_args__ = (UniqueConstraint("source_provider", "source_record_id", name="uq_competition_source"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_competition_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    country: Mapped[str | None] = mapped_column(String(128))
    region: Mapped[str | None] = mapped_column(String(128))
    competition_type: Mapped[CompetitionType] = mapped_column(default=CompetitionType.UNKNOWN, nullable=False)
    division_level: Mapped[int | None] = mapped_column(Integer)
    competition_format: Mapped[CompetitionFormat] = mapped_column(
        default=CompetitionFormat.UNKNOWN, nullable=False
    )
    status: Mapped[CompetitionStatus] = mapped_column(default=CompetitionStatus.DISCOVERED, nullable=False)
    data_quality_status: Mapped[DataQualityStatus] = mapped_column(
        default=DataQualityStatus.INSUFFICIENT, nullable=False
    )
    number_of_teams: Mapped[int | None] = mapped_column(Integer)

    seasons: Mapped[list["Season"]] = relationship(back_populates="competition", cascade="all, delete-orphan")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Competition {self.canonical_competition_id} {self.name!r} status={self.status}>"


class Season(Base, TimestampMixin, ProvenanceMixin):
    __tablename__ = "seasons"
    __table_args__ = (
        UniqueConstraint("competition_id", "canonical_season_id", name="uq_season_per_competition"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"), nullable=False, index=True)
    canonical_season_id: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    start_date: Mapped[dt.date | None] = mapped_column(Date)
    end_date: Mapped[dt.date | None] = mapped_column(Date)
    status: Mapped[SeasonStatus] = mapped_column(default=SeasonStatus.UPCOMING, nullable=False)

    competition: Mapped[Competition] = relationship(back_populates="seasons")

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Season {self.canonical_season_id} competition={self.competition_id} status={self.status}>"
