"""Fixtures, results, match statistics and xG — MASTER BUILD PROMPT section 11."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.models.enums import FixtureStatus
from app.database.models.mixins import ProvenanceMixin, TimestampMixin


class Fixture(Base, TimestampMixin, ProvenanceMixin):
    __tablename__ = "fixtures"
    __table_args__ = (UniqueConstraint("source_provider", "source_record_id", name="uq_fixture_source"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    canonical_fixture_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"), nullable=False, index=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), nullable=False, index=True)
    round: Mapped[str | None] = mapped_column(String(64))
    kickoff_utc: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    home_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    away_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    venue: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[FixtureStatus] = mapped_column(default=FixtureStatus.SCHEDULED, nullable=False)

    result: Mapped["Result | None"] = relationship(back_populates="fixture", uselist=False, cascade="all, delete-orphan")
    statistics: Mapped[list["MatchStatistic"]] = relationship(back_populates="fixture", cascade="all, delete-orphan")
    xg: Mapped["XGData | None"] = relationship(back_populates="fixture", uselist=False, cascade="all, delete-orphan")


class Result(Base, TimestampMixin, ProvenanceMixin):
    __tablename__ = "results"

    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), unique=True, nullable=False)
    home_goals: Mapped[int] = mapped_column(Integer, nullable=False)
    away_goals: Mapped[int] = mapped_column(Integer, nullable=False)
    home_goals_first_half: Mapped[int | None] = mapped_column(Integer)
    away_goals_first_half: Mapped[int | None] = mapped_column(Integer)

    fixture: Mapped[Fixture] = relationship(back_populates="result")


class MatchStatistic(Base, TimestampMixin, ProvenanceMixin):
    """Free-form match statistics (shots, corners, cards, possession, ...)."""

    __tablename__ = "match_statistics"
    __table_args__ = (UniqueConstraint("fixture_id", "stat_name", "team_id", name="uq_match_stat"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), nullable=False, index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    stat_name: Mapped[str] = mapped_column(String(64), nullable=False)
    stat_value: Mapped[float] = mapped_column(Float, nullable=False)

    fixture: Mapped[Fixture] = relationship(back_populates="statistics")


class XGData(Base, TimestampMixin, ProvenanceMixin):
    __tablename__ = "xg_data"

    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), unique=True, nullable=False)
    home_xg: Mapped[float | None] = mapped_column(Float)
    away_xg: Mapped[float | None] = mapped_column(Float)
    home_xg_first_half: Mapped[float | None] = mapped_column(Float)
    away_xg_first_half: Mapped[float | None] = mapped_column(Float)
    shot_level_data: Mapped[dict | None] = mapped_column(JSON)

    fixture: Mapped[Fixture] = relationship(back_populates="xg")
