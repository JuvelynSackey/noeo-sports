"""Prediction registry, pre-match snapshots and scenario predictions.

MASTER BUILD PROMPT sections 46, 47, 43.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import JSON, DateTime, Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base
from app.database.models.enums import DisagreementLevel, ForecastStatus
from app.database.models.mixins import TimestampMixin, utcnow


def _new_prediction_id() -> str:
    return str(uuid.uuid4())


class Prediction(Base, TimestampMixin):
    __tablename__ = "predictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[str] = mapped_column(String(36), unique=True, index=True, default=_new_prediction_id)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), nullable=False, index=True)
    predicted_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    model_version_id: Mapped[int] = mapped_column(ForeignKey("model_versions.id"), nullable=False, index=True)
    dataset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    feature_version: Mapped[str] = mapped_column(String(64), nullable=False)
    software_version: Mapped[str] = mapped_column(String(64), nullable=False)

    score_matrix: Mapped[dict] = mapped_column(JSON, nullable=False)
    expected_goals_home: Mapped[float | None] = mapped_column(Float)
    expected_goals_away: Mapped[float | None] = mapped_column(Float)
    outcome_probabilities: Mapped[dict] = mapped_column(JSON, nullable=False)
    goal_distribution: Mapped[dict | None] = mapped_column(JSON)

    forecast_status: Mapped[ForecastStatus] = mapped_column(default=ForecastStatus.FAILED_VALIDATION, nullable=False)
    validation_report: Mapped[dict | None] = mapped_column(JSON)

    aleatoric_uncertainty: Mapped[float | None] = mapped_column(Float)
    epistemic_uncertainty: Mapped[float | None] = mapped_column(Float)
    data_quality_score: Mapped[float | None] = mapped_column(Float)
    model_disagreement_level: Mapped[DisagreementLevel | None] = mapped_column()
    ood_status: Mapped[bool] = mapped_column(default=False, nullable=False)

    snapshot: Mapped["PredictionSnapshot | None"] = relationship(
        back_populates="prediction", uselist=False, cascade="all, delete-orphan"
    )


class PredictionSnapshot(Base, TimestampMixin):
    """Frozen inputs available at prediction time — section 47."""

    __tablename__ = "prediction_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"), unique=True, nullable=False)
    data_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False)
    features: Mapped[dict] = mapped_column(JSON, nullable=False)
    model_configuration: Mapped[dict] = mapped_column(JSON, nullable=False)
    snapshot_taken_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)

    prediction: Mapped[Prediction] = relationship(back_populates="snapshot")


class ScenarioPrediction(Base, TimestampMixin):
    """What-if analysis — section 43. Never mutates the baseline forecast."""

    __tablename__ = "scenario_predictions"

    id: Mapped[int] = mapped_column(primary_key=True)
    fixture_id: Mapped[int] = mapped_column(ForeignKey("fixtures.id"), nullable=False, index=True)
    baseline_prediction_id: Mapped[int] = mapped_column(ForeignKey("predictions.id"), nullable=False)
    scenario_name: Mapped[str] = mapped_column(String(255), nullable=False)
    assumptions: Mapped[dict] = mapped_column(JSON, nullable=False)
    scenario_result: Mapped[dict] = mapped_column(JSON, nullable=False)
    difference: Mapped[dict] = mapped_column(JSON, nullable=False)
    requested_by: Mapped[str | None] = mapped_column(String(255))
