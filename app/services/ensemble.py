"""Ensemble weight learning — MASTER BUILD PROMPT section 34.

Weights are learned from pooled walk-forward out-of-sample predictions
(`app/services/backtesting.py`, section 35) across every candidate model:
each candidate's ensemble weight is set from its relative mean log-loss
over every fold's held-out matches via a softmax — never assigned by hand
because a model "seems" better. This superseded Phase 6's original
single train/validation split with the more robust walk-forward estimate.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.models.competitions import Competition
from app.database.models.modeling import ModelVersion, ModelWeight
from app.services.backtesting import CANDIDATES, BacktestReport, BacktestingService


@dataclass
class CandidateResult:
    model_name: str
    report: BacktestReport
    weight: float = 0.0


@dataclass
class EnsembleTrainingReport:
    competition_canonical_id: str
    trained: bool
    candidates: list[CandidateResult] = field(default_factory=list)
    skipped_reason: str | None = None


class EnsembleService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def train(self, competition: Competition, backtest_reports: dict[str, BacktestReport] | None = None) -> EnsembleTrainingReport:
        report = EnsembleTrainingReport(competition_canonical_id=competition.canonical_competition_id, trained=False)

        backtest_reports = backtest_reports if backtest_reports is not None else BacktestingService(self.db, self.settings).run_all(competition)

        candidates = [
            CandidateResult(model_name=name, report=backtest_reports[name])
            for name, _ in CANDIDATES
            if name in backtest_reports
            and backtest_reports[name].completed
            and len(backtest_reports[name].predictions) >= self.settings.ensemble_min_validation_matches
        ]

        if not candidates:
            any_report = next(iter(backtest_reports.values()), None)
            report.skipped_reason = (
                any_report.skipped_reason if any_report and any_report.skipped_reason else "no candidate had enough walk-forward predictions"
            )
            self._clear_weights(competition)
            return report

        # Softmax over negative log-loss: lower held-out loss -> higher weight.
        losses = np.array([c.report.metrics.mean_log_loss for c in candidates])
        raw = np.exp(-(losses - losses.min()))
        weights = raw / raw.sum()
        for c, w in zip(candidates, weights):
            c.weight = float(w)

        self._persist_weights(competition, candidates)

        report.trained = True
        report.candidates = candidates
        return report

    def _persist_weights(self, competition: Competition, candidates: list[CandidateResult]) -> None:
        self._clear_weights(competition)
        for c in candidates:
            model_version = (
                self.db.query(ModelVersion)
                .filter_by(model_name=c.model_name, competition_id=competition.id, status="ENABLED")
                .order_by(ModelVersion.trained_at.desc())
                .first()
            )
            if model_version is None:
                continue  # candidate scored on the backtest but has no live production version
            kickoffs = [p.kickoff for p in c.report.predictions]
            self.db.add(
                ModelWeight(
                    model_version_id=model_version.id,
                    competition_id=competition.id,
                    weight=c.weight,
                    learned_from_window_start=min(kickoffs) if kickoffs else None,
                    learned_from_window_end=max(kickoffs) if kickoffs else None,
                )
            )
        self.db.commit()

    def _clear_weights(self, competition: Competition) -> None:
        candidate_names = [name for name, _ in CANDIDATES]
        existing = (
            self.db.query(ModelWeight)
            .join(ModelVersion, ModelWeight.model_version_id == ModelVersion.id)
            .filter(ModelWeight.competition_id == competition.id, ModelVersion.model_name.in_(candidate_names))
            .all()
        )
        for w in existing:
            self.db.delete(w)
        if existing:
            self.db.commit()
