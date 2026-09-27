"""Walk-forward backtesting — MASTER BUILD PROMPT section 35.

Chronological, expanding-window evaluation: train on everything up to a
point in time, predict the next fold of matches out-of-sample, fold those
matches' actual results into the training set, repeat. This is "the main
evaluation method" the spec calls for, never a random train/test split,
because it's the only scheme that can't leak future information — every
recorded prediction was made using strictly earlier data than the match it
predicts, and each fold's model is refit from scratch on exactly the data
that would genuinely have been available at that point in time.

This module is the shared source of out-of-sample predictions for both
ensemble weight learning (`ensemble.py`) and calibration fitting
(`calibration.py`) — Phase 6 originally gave each of those a single
train/validation split of its own; this supersedes both with pooled
predictions across many folds, a materially more robust estimate.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.models.competitions import Competition
from app.database.models.enums import FixtureStatus
from app.database.models.fixtures import Fixture, Result
from app.database.models.modeling import CalibrationResult, ModelVersion
from app.database.models.teams import Team
from app.evaluation.metrics import (
    AWAY,
    DRAW,
    HOME,
    ValidationMetrics,
    evaluate_predictions,
    expected_calibration_error,
    reliability_curve,
)
from app.forecasting.score_matrix import build_score_matrix, expected_goals_from_matrix, outcome_probabilities
from app.logging_config import get_logger
from app.models.goal_model import GoalMatchRecord, GoalModel
from app.services.hierarchical_shrinkage import shrink_fit

logger = get_logger(__name__)

# (model_name, use_dc_adjustment) — the goal-based candidates backtested,
# ensembled, and calibrated together. Corners/cards/first-half/xG predict
# different markets entirely and aren't part of this pool.
CANDIDATES: list[tuple[str, bool]] = [
    ("dixon_coles", True),
    ("poisson_baseline", False),
    ("hierarchical_model", True),
]


@dataclass(frozen=True)
class FoldPrediction:
    kickoff: dt.datetime
    predicted_outcome: tuple[float, float, float]  # (home_win, draw, away_win)
    actual_outcome_index: int
    exact_score_probability: float
    exact_score_log_loss: float
    predicted_home_goals: float
    predicted_away_goals: float
    actual_home_goals: int
    actual_away_goals: int


@dataclass
class BacktestReport:
    competition_canonical_id: str
    model_name: str
    completed: bool
    n_folds: int = 0
    predictions: list[FoldPrediction] = field(default_factory=list)
    metrics: ValidationMetrics | None = None
    calibration_error: float | None = None
    reliability_curve: list[dict] = field(default_factory=list)
    exact_score_mean_log_loss: float | None = None
    exact_score_mean_probability: float | None = None
    home_goal_residual_mean: float | None = None
    home_goal_residual_std: float | None = None
    away_goal_residual_mean: float | None = None
    away_goal_residual_std: float | None = None
    total_goals_rmse: float | None = None
    skipped_reason: str | None = None


class BacktestingService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def run_all(self, competition: Competition, candidates: list[tuple[str, bool]] | None = None) -> dict[str, BacktestReport]:
        candidates = candidates if candidates is not None else CANDIDATES
        return {model_name: self.run(competition, model_name, use_dc) for model_name, use_dc in candidates}

    def run(self, competition: Competition, model_name: str, use_dc_adjustment: bool) -> BacktestReport:
        report = BacktestReport(competition_canonical_id=competition.canonical_competition_id, model_name=model_name, completed=False)

        completed_matches = (
            self.db.query(Fixture, Result)
            .join(Result, Result.fixture_id == Fixture.id)
            .filter(
                Fixture.competition_id == competition.id,
                Fixture.status == FixtureStatus.COMPLETED,
                Fixture.kickoff_utc.isnot(None),
            )
            .order_by(Fixture.kickoff_utc)
            .all()
        )

        n = len(completed_matches)
        initial_train = self.settings.backtest_initial_train_matches
        fold_size = self.settings.backtest_fold_size
        if n < initial_train + fold_size:
            report.skipped_reason = (
                f"insufficient data for walk-forward backtesting ({n} completed matches; "
                f"need >= {initial_train + fold_size})"
            )
            return report

        team_row_ids = sorted({f.home_team_id for f, _ in completed_matches} | {f.away_team_id for f, _ in completed_matches})
        teams_by_id = {t.id: t for t in self.db.query(Team).filter(Team.id.in_(team_row_ids)).all()}
        team_ids = [teams_by_id[tid].canonical_team_id for tid in team_row_ids]
        index_of = {row_id: i for i, row_id in enumerate(team_row_ids)}

        def to_record(f, r) -> GoalMatchRecord:
            return GoalMatchRecord(index_of[f.home_team_id], index_of[f.away_team_id], r.home_goals, r.away_goals)

        predictions: list[FoldPrediction] = []
        n_folds = 0
        start = initial_train
        while start < n:
            fold_end = min(start + fold_size, n)
            train_rows = completed_matches[:start]
            fold_rows = completed_matches[start:fold_end]
            n_folds += 1

            train_matches = [to_record(f, r) for f, r in train_rows]
            games_played = {tid: 0 for tid in team_ids}
            for f, _ in train_rows:
                games_played[teams_by_id[f.home_team_id].canonical_team_id] += 1
                games_played[teams_by_id[f.away_team_id].canonical_team_id] += 1

            try:
                model = GoalModel(use_dc_adjustment=use_dc_adjustment, l2_regularization=self.settings.model_l2_regularization)
                fit = model.fit(team_ids, train_matches)
                if model_name == "hierarchical_model":
                    fit = shrink_fit(fit, games_played, self.settings)
            except Exception as exc:  # a single bad fold must not abort the whole backtest
                logger.warning("backtest_fold_fit_failed", model_name=model_name, error=str(exc))
                start = fold_end
                continue

            for f, r in fold_rows:
                home_id = teams_by_id[f.home_team_id].canonical_team_id
                away_id = teams_by_id[f.away_team_id].canonical_team_id
                if home_id not in fit.attack or away_id not in fit.attack:
                    continue  # team never appeared in this fold's training window

                score = build_score_matrix(
                    model,
                    fit,
                    home_id,
                    away_id,
                    initial_max_goals=self.settings.score_matrix_initial_max_goals,
                    tail_threshold=self.settings.score_matrix_tail_threshold,
                    max_goals_cap=self.settings.score_matrix_max_goals_cap,
                )
                outcomes = outcome_probabilities(score.matrix)
                pred_home, pred_away = expected_goals_from_matrix(score.matrix)

                max_goals = score.matrix.shape[0] - 1
                hg, ag = min(r.home_goals, max_goals), min(r.away_goals, max_goals)
                exact_p = max(float(score.matrix[hg, ag]), 1e-12)
                actual_idx = HOME if r.home_goals > r.away_goals else (DRAW if r.home_goals == r.away_goals else AWAY)

                predictions.append(
                    FoldPrediction(
                        kickoff=f.kickoff_utc,
                        predicted_outcome=(outcomes["home_win"], outcomes["draw"], outcomes["away_win"]),
                        actual_outcome_index=actual_idx,
                        exact_score_probability=exact_p,
                        exact_score_log_loss=-float(np.log(exact_p)),
                        predicted_home_goals=pred_home,
                        predicted_away_goals=pred_away,
                        actual_home_goals=r.home_goals,
                        actual_away_goals=r.away_goals,
                    )
                )

            start = fold_end

        if not predictions:
            report.skipped_reason = "no scoreable out-of-sample predictions across any fold"
            return report

        report.predictions = predictions
        report.n_folds = n_folds
        report.metrics = evaluate_predictions([p.predicted_outcome for p in predictions], [p.actual_outcome_index for p in predictions])

        home_win_probs = [p.predicted_outcome[HOME] for p in predictions]
        home_win_actual = [p.actual_outcome_index == HOME for p in predictions]
        report.calibration_error = expected_calibration_error(home_win_probs, home_win_actual)
        report.reliability_curve = reliability_curve(home_win_probs, home_win_actual)

        report.exact_score_mean_log_loss = float(np.mean([p.exact_score_log_loss for p in predictions]))
        report.exact_score_mean_probability = float(np.mean([p.exact_score_probability for p in predictions]))

        home_residuals = np.array([p.actual_home_goals - p.predicted_home_goals for p in predictions])
        away_residuals = np.array([p.actual_away_goals - p.predicted_away_goals for p in predictions])
        report.home_goal_residual_mean = float(home_residuals.mean())
        report.home_goal_residual_std = float(home_residuals.std())
        report.away_goal_residual_mean = float(away_residuals.mean())
        report.away_goal_residual_std = float(away_residuals.std())

        actual_totals = np.array([p.actual_home_goals + p.actual_away_goals for p in predictions])
        predicted_totals = np.array([p.predicted_home_goals + p.predicted_away_goals for p in predictions])
        report.total_goals_rmse = float(np.sqrt(np.mean((actual_totals - predicted_totals) ** 2)))

        report.completed = True
        self._persist(competition, model_name, report)
        return report

    def _persist(self, competition: Competition, model_name: str, report: BacktestReport) -> None:
        model_version = (
            self.db.query(ModelVersion)
            .filter_by(model_name=model_name, competition_id=competition.id, status="ENABLED")
            .order_by(ModelVersion.trained_at.desc())
            .first()
        )
        if model_version is None:
            return  # backtest completed on historical data, but nothing live to attach the result to

        record = (
            self.db.query(CalibrationResult)
            .filter_by(model_version_id=model_version.id, competition_id=competition.id, forecast_type="walk_forward_backtest")
            .first()
        )
        if record is None:
            record = CalibrationResult(
                model_version_id=model_version.id, competition_id=competition.id, forecast_type="walk_forward_backtest"
            )
            self.db.add(record)
        record.method = model_name
        record.brier_score = report.metrics.mean_brier_score
        record.log_loss = report.metrics.mean_log_loss
        record.ranked_probability_score = report.metrics.mean_rps
        record.calibration_error = report.calibration_error
        record.reliability_curve = {
            "points": report.reliability_curve,
            "n_folds": report.n_folds,
            "n_predictions": len(report.predictions),
            "exact_score_mean_log_loss": report.exact_score_mean_log_loss,
            "exact_score_mean_probability": report.exact_score_mean_probability,
            "home_goal_residual_mean": report.home_goal_residual_mean,
            "home_goal_residual_std": report.home_goal_residual_std,
            "away_goal_residual_mean": report.away_goal_residual_mean,
            "away_goal_residual_std": report.away_goal_residual_std,
            "total_goals_rmse": report.total_goals_rmse,
        }
        record.evaluated_at = dt.datetime.now(dt.timezone.utc)
        self.db.commit()
