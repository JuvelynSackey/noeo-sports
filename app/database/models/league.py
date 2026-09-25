"""League baselines and dynamic team strength — MASTER BUILD PROMPT sections 16, 21, 23."""
from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.models.mixins import TimestampMixin, utcnow


class LeagueParameter(Base, TimestampMixin):
    """League-specific statistical baseline for one competition+season."""

    __tablename__ = "league_parameters"
    __table_args__ = (UniqueConstraint("competition_id", "season_id", name="uq_league_parameter"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"), nullable=False, index=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), nullable=False, index=True)

    avg_home_goals: Mapped[float | None] = mapped_column(Float)
    avg_away_goals: Mapped[float | None] = mapped_column(Float)
    avg_total_goals: Mapped[float | None] = mapped_column(Float)
    home_advantage: Mapped[float | None] = mapped_column(Float)
    draw_frequency: Mapped[float | None] = mapped_column(Float)
    scoring_variance: Mapped[float | None] = mapped_column(Float)
    sample_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    shrinkage_applied: Mapped[bool] = mapped_column(default=False, nullable=False)
    computed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class TeamStrength(Base, TimestampMixin):
    """Dynamic team-strength snapshot — MASTER BUILD PROMPT section 21."""

    __tablename__ = "team_strength"
    __table_args__ = (UniqueConstraint("team_id", "competition_id", "as_of", name="uq_team_strength_snapshot"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"), nullable=False, index=True)
    as_of: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)

    attack_strength: Mapped[float | None] = mapped_column(Float)
    defence_strength: Mapped[float | None] = mapped_column(Float)
    home_strength: Mapped[float | None] = mapped_column(Float)
    away_strength: Mapped[float | None] = mapped_column(Float)
    opponent_adjusted_strength: Mapped[float | None] = mapped_column(Float)
    recent_strength: Mapped[float | None] = mapped_column(Float)
    uncertainty: Mapped[float | None] = mapped_column(Float)
    method: Mapped[str | None] = mapped_column(String(64))
    shrinkage_source: Mapped[str | None] = mapped_column(String(255))
    extra: Mapped[dict | None] = mapped_column(JSON)
