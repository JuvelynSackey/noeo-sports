"""Model versions, ensemble weights and calibration results.

MASTER BUILD PROMPT sections 17, 34, 37, 45.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.models.enums import ModelStatus
from app.database.models.mixins import TimestampMixin, utcnow


class ModelVersion(Base, TimestampMixin):
    __tablename__ = "model_versions"
    __table_args__ = (UniqueConstraint("model_name", "version", name="uq_model_version"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    model_name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[ModelStatus] = mapped_column(default=ModelStatus.DISABLED, nullable=False)
    disabled_reason: Mapped[str | None] = mapped_column(String(500))
    competition_id: Mapped[int | None] = mapped_column(ForeignKey("competitions.id"), index=True)
    trained_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    training_window_start: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    training_window_end: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    hyperparameters: Mapped[dict | None] = mapped_column(JSON)
    parameters: Mapped[dict | None] = mapped_column(JSON)
    evaluation_metrics: Mapped[dict | None] = mapped_column(JSON)
    is_reproducible: Mapped[bool] = mapped_column(default=True, nullable=False)
    random_seed: Mapped[int | None] = mapped_column()

    weights: Mapped[list["ModelWeight"]] = relationship(back_populates="model_version", cascade="all, delete-orphan")


class ModelWeight(Base, TimestampMixin):
    """Ensemble weight of one model version within one competition's ensemble."""

    __tablename__ = "model_weights"
    __table_args__ = (UniqueConstraint("model_version_id", "competition_id", name="uq_model_weight"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"), nullable=False, index=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"), nullable=False, index=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    learned_from_window_start: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    learned_from_window_end: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))

    model_version: Mapped[ModelVersion] = relationship(back_populates="weights")


class CalibrationResult(Base, TimestampMixin):
    __tablename__ = "calibration_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"), nullable=False, index=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"), nullable=False, index=True)
    season_id: Mapped[int | None] = mapped_column(ForeignKey("seasons.id"), index=True)
    forecast_type: Mapped[str] = mapped_column(String(64), nullable=False)
    method: Mapped[str] = mapped_column(String(64), nullable=False)
    brier_score: Mapped[float | None] = mapped_column(Float)
    log_loss: Mapped[float | None] = mapped_column(Float)
    ranked_probability_score: Mapped[float | None] = mapped_column(Float)
    calibration_error: Mapped[float | None] = mapped_column(Float)
    reliability_curve: Mapped[dict | None] = mapped_column(JSON)
    # The fitted transform itself (isotonic breakpoints, Platt/beta coefficients),
    # so it can be reapplied to future forecasts rather than only measured.
    calibration_map: Mapped[dict | None] = mapped_column(JSON)
    evaluated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ConformalCalibration(Base, TimestampMixin):
    """Distribution-free (conformal) uncertainty calibration — section 44.
    Upserted per (model_version, competition, target), mirroring
    CalibrationResult's overwrite-in-place semantics rather than
    ModelMonitoring's append-only history, since this is "the current best
    calibration for this model," not a time series."""

    __tablename__ = "conformal_calibrations"
    __table_args__ = (UniqueConstraint("model_version_id", "competition_id", "target", name="uq_conformal_calibration"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"), nullable=False, index=True)
    competition_id: Mapped[int] = mapped_column(ForeignKey("competitions.id"), nullable=False, index=True)
    target: Mapped[str] = mapped_column(String(64), nullable=False)  # home_goals | away_goals | total_goals | outcome
    method: Mapped[str] = mapped_column(String(64), nullable=False, default="split_conformal")
    alpha: Mapped[float] = mapped_column(Float, nullable=False)
    # Regression targets: the interval's half-width. Classification (outcome)
    # target: the nonconformity threshold tau. One field serves both, since
    # both are simply "the calibrated split-conformal quantile."
    quantile: Mapped[float] = mapped_column(Float, nullable=False)
    n_calibration: Mapped[int] = mapped_column(nullable=False)
    n_test: Mapped[int] = mapped_column(nullable=False)
    empirical_coverage: Mapped[float | None] = mapped_column(Float)
    evaluated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
