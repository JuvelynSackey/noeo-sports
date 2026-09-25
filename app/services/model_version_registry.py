"""Shared ModelVersion persistence.

Every model-fitting service (Dixon-Coles/Poisson, first-half, corners,
cards, hierarchical) goes through these three functions so `/models`
behaves consistently regardless of which one produced a row: retiring the
previous ENABLED version rather than deleting it, and recording a
human-readable reason whenever a model has to stay DISABLED.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy.orm import Session

from app.config import Settings
from app.database.models.competitions import Competition
from app.database.models.enums import ModelStatus
from app.database.models.modeling import ModelVersion
from app.models.goal_model import GoalModelFit


def retire_active(db: Session, model_name: str, competition: Competition) -> None:
    active = (
        db.query(ModelVersion)
        .filter_by(model_name=model_name, competition_id=competition.id, status=ModelStatus.ENABLED)
        .all()
    )
    for m in active:
        m.status = ModelStatus.RETIRED
    if active:
        db.commit()


def record_disabled(db: Session, model_name: str, competition: Competition, reason: str | None) -> None:
    retire_active(db, model_name, competition)
    existing = (
        db.query(ModelVersion)
        .filter_by(model_name=model_name, competition_id=competition.id, status=ModelStatus.DISABLED)
        .first()
    )
    if existing is not None:
        existing.disabled_reason = reason
        db.commit()
        return
    db.add(
        ModelVersion(
            model_name=model_name,
            version=uuid.uuid4().hex[:12],
            status=ModelStatus.DISABLED,
            disabled_reason=reason,
            competition_id=competition.id,
        )
    )
    db.commit()


def persist_goal_fit(
    db: Session,
    settings: Settings,
    model_name: str,
    competition: Competition,
    fit: GoalModelFit,
    window_start: dt.datetime | None,
    window_end: dt.datetime | None,
    use_dc_adjustment: bool,
) -> str:
    retire_active(db, model_name, competition)
    version = uuid.uuid4().hex[:12]
    db.add(
        ModelVersion(
            model_name=model_name,
            version=version,
            status=ModelStatus.ENABLED,
            competition_id=competition.id,
            trained_at=dt.datetime.now(dt.timezone.utc),
            training_window_start=window_start,
            training_window_end=window_end,
            hyperparameters={
                "l2_regularization": settings.model_l2_regularization,
                "use_dc_adjustment": use_dc_adjustment,
            },
            parameters={
                "attack": fit.attack,
                "defence": fit.defence,
                "home_advantage": fit.home_advantage,
                "rho": fit.rho,
                "team_ids": fit.team_ids,
            },
            evaluation_metrics={
                "log_likelihood": fit.log_likelihood,
                "aic": fit.aic,
                "n_matches": fit.n_matches,
                "n_params": fit.n_params,
                "converged": fit.converged,
            },
            is_reproducible=True,
        )
    )
    db.commit()
    return version
