"""Conformal (distribution-free) uncertainty calibration — MASTER BUILD
PROMPT section 44.

Mirrors calibration.py's shape exactly: it consumes the champion
`dixon_coles` model's pooled walk-forward out-of-sample predictions
(`app/services/backtesting.py`, section 35) rather than refitting anything
of its own, and is skipped — not defaulted to some made-up interval — when
there isn't enough out-of-sample data to calibrate trustworthily. The
calibration/test split is chronological (earlier matches calibrate, later
matches test), consistent with the rest of the project's "no future
information" rule, rather than a random split.

Calibrated against dixon_coles's own predictions specifically, not the
published ensemble blend — the same anchor-model simplification
`forecast_service.py` already documents for its quality gate. Extending
this to calibrate directly against the ensemble's pooled out-of-sample
predictions is a natural follow-up, not something this phase needed to do.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.models.competitions import Competition
from app.database.models.modeling import ConformalCalibration, ModelVersion
from app.evaluation.conformal import fit_classification_conformal, fit_regression_conformal
from app.services.backtesting import BacktestReport, BacktestingService

HOME_GOALS = "home_goals"
AWAY_GOALS = "away_goals"
TOTAL_GOALS = "total_goals"
OUTCOME = "outcome"
TARGETS = (HOME_GOALS, AWAY_GOALS, TOTAL_GOALS, OUTCOME)


@dataclass
class ConformalTrainingReport:
    competition_canonical_id: str
    fitted: bool
    targets_fitted: list[str] = field(default_factory=list)
    n_calibration: int = 0
    n_test: int = 0
    skipped_reason: str | None = None


class ConformalCalibrationService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def train(
        self, competition: Competition, backtest_reports: dict[str, BacktestReport] | None = None
    ) -> ConformalTrainingReport:
        report = ConformalTrainingReport(competition_canonical_id=competition.canonical_competition_id, fitted=False)

        champion = (
            self.db.query(ModelVersion)
            .filter_by(model_name="dixon_coles", competition_id=competition.id, status="ENABLED")
            .order_by(ModelVersion.trained_at.desc())
            .first()
        )
        if champion is None:
            report.skipped_reason = "no ENABLED dixon_coles model to calibrate"
            return report

        if backtest_reports is not None and "dixon_coles" in backtest_reports:
            backtest = backtest_reports["dixon_coles"]
        else:
            backtest = BacktestingService(self.db, self.settings).run(competition, "dixon_coles", True)

        threshold = self.settings.conformal_min_predictions
        predictions = sorted(backtest.predictions, key=lambda p: p.kickoff) if backtest.completed else []
        if not backtest.completed or len(predictions) < threshold:
            report.skipped_reason = backtest.skipped_reason or f"only {len(predictions)} out-of-sample predictions available (< {threshold})"
            return report

        split = max(1, int(len(predictions) * self.settings.conformal_calibration_fraction))
        calibration, test = predictions[:split], predictions[split:]
        alpha = self.settings.conformal_alpha

        regression_targets = {
            HOME_GOALS: lambda p: abs(p.actual_home_goals - p.predicted_home_goals),
            AWAY_GOALS: lambda p: abs(p.actual_away_goals - p.predicted_away_goals),
            TOTAL_GOALS: lambda p: abs(
                (p.actual_home_goals + p.actual_away_goals) - (p.predicted_home_goals + p.predicted_away_goals)
            ),
        }
        for target, residual_fn in regression_targets.items():
            result = fit_regression_conformal(
                [residual_fn(p) for p in calibration], [residual_fn(p) for p in test], alpha
            )
            self._persist(champion, competition, target, alpha, result.quantile, result.n_calibration, result.n_test, result.empirical_coverage)
            report.targets_fitted.append(target)

        def _nonconformity(p) -> float:
            return 1.0 - p.predicted_outcome[p.actual_outcome_index]

        outcome_result = fit_classification_conformal(
            [_nonconformity(p) for p in calibration], [_nonconformity(p) for p in test], alpha
        )
        self._persist(
            champion, competition, OUTCOME, alpha, outcome_result.threshold,
            outcome_result.n_calibration, outcome_result.n_test, outcome_result.empirical_coverage,
        )
        report.targets_fitted.append(OUTCOME)

        report.fitted = True
        report.n_calibration = len(calibration)
        report.n_test = len(test)
        return report

    def _persist(
        self,
        champion: ModelVersion,
        competition: Competition,
        target: str,
        alpha: float,
        quantile: float,
        n_calibration: int,
        n_test: int,
        empirical_coverage: float | None,
    ) -> None:
        record = (
            self.db.query(ConformalCalibration)
            .filter_by(model_version_id=champion.id, competition_id=competition.id, target=target)
            .first()
        )
        if record is None:
            record = ConformalCalibration(model_version_id=champion.id, competition_id=competition.id, target=target)
            self.db.add(record)
        record.method = "split_conformal"
        record.alpha = alpha
        record.quantile = quantile
        record.n_calibration = n_calibration
        record.n_test = n_test
        record.empirical_coverage = empirical_coverage
        record.evaluated_at = dt.datetime.now(dt.timezone.utc)
        self.db.commit()
