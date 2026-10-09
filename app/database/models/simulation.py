"""Monte Carlo season simulation — MASTER BUILD PROMPT section 42.

A `SimulationRun` is one reproducible scenario (recorded seed, model
version, feature/software version, input snapshot, configuration — exactly
section 42's required fields); its `standings` are the aggregated
per-team outcome of every simulated iteration, never a single sampled
season.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.models.mixins import TimestampMixin


class SimulationRun(Base, TimestampMixin):
    __tablename__ = "simulation_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    scenario_id: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"), nullable=False, index=True)
    season_id: Mapped[int] = mapped_column(ForeignKey("seasons.id"), nullable=False, index=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"), nullable=False, index=True)
    n_simulations: Mapped[int] = mapped_column(Integer, nullable=False)
    random_seed: Mapped[int] = mapped_column(nullable=False)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    software_version: Mapped[str] = mapped_column(String(32), nullable=False)
    configuration: Mapped[dict] = mapped_column(JSON, nullable=False)
    input_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    n_remaining_fixtures: Mapped[int] = mapped_column(Integer, nullable=False)
    n_unscoreable_fixtures: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    standings: Mapped[list["SimulationStandingResult"]] = relationship(
        back_populates="simulation_run", cascade="all, delete-orphan"
    )


class SimulationStandingResult(Base, TimestampMixin):
    __tablename__ = "simulation_standing_results"
    __table_args__ = (UniqueConstraint("simulation_run_id", "team_id", name="uq_simulation_standing"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    simulation_run_id: Mapped[int] = mapped_column(ForeignKey("simulation_runs.id"), nullable=False, index=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), nullable=False, index=True)
    mean_points: Mapped[float] = mapped_column(Float, nullable=False)
    mean_position: Mapped[float] = mapped_column(Float, nullable=False)
    position_probabilities: Mapped[dict] = mapped_column(JSON, nullable=False)  # {"1": 0.12, "2": 0.08, ...}
    title_probability: Mapped[float] = mapped_column(Float, nullable=False)
    top_n_probability: Mapped[float] = mapped_column(Float, nullable=False)
    relegation_probability: Mapped[float] = mapped_column(Float, nullable=False)

    simulation_run: Mapped[SimulationRun] = relationship(back_populates="standings")
