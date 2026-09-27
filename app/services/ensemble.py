"""Ensemble weight learning — MASTER BUILD PROMPT section 34.

Weights are learned from a chronological holdout split of each
competition's own completed matches: the earliest ones train each
candidate model, the most recent ones score it out-of-sample, and each
candidate's ensemble weight is set from its relative validation log-loss
via a softmax — never assigned by hand because a model "seems" better.
This is a single-split holdout, not yet the full rolling walk-forward
evaluation of Phase 7, which will supersede it with a more robust estimate
once that infrastructure exists.
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
from app.database.models.modeling import CalibrationResult, ModelVersion, ModelWeight
from app.database.models.teams import Team
from app.evaluation.metrics import AWAY, DRAW, HOME, ValidationMetrics, evaluate_predictions
from app.forecasting.score_matrix import build_score_matrix, outcome_probabilities
from app.logging_config import get_logger
from app.models.goal_model import GoalMatchRecord, GoalModel
from app.services.hierarchical_shrinkage import shrink_fit

logger = get_logger(__name__)

# (model_name, use_dc_adjustment) — the goal-based candidates this ensemble
# blends. Corners/cards/first-half/xG predict different markets entirely and
# aren't part of this pool.
CANDIDATES: list[tuple[str, bool]] = [
    ("dixon_coles", True),
    ("poisson_baseline", False),
    ("hierarchical_model", True),
]


@dataclass
class CandidateResult:
    model_name: str
    metrics: ValidationMetrics
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

    def train(self, competition: Competition) -> EnsembleTrainingReport:
        report = EnsembleTrainingReport(competition_canonical_id=competition.canonical_competition_id, trained=False)

        completed = (
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

        n = len(completed)
        val_size = max(
            int(round(n * self.settings.ensemble_validation_fraction)), self.settings.ensemble_min_validation_matches
        )
        train_size = n - val_size

        if train_size < self.settings.ensemble_min_train_matches or val_size < self.settings.ensemble_min_validation_matches:
            report.skipped_reason = (
                f"insufficient data for a holdout split ({n} completed matches; need >= "
                f"{self.settings.ensemble_min_train_matches} train + "
                f"{self.settings.ensemble_min_validation_matches} validation)"
            )
            self._clear_weights(competition)
            return report

        train_rows = completed[:train_size]
        val_rows = completed[train_size:]

        team_row_ids = sorted({f.home_team_id for f, _ in completed} | {f.away_team_id for f, _ in completed})
        teams_by_id = {t.id: t for t in self.db.query(Team).filter(Team.id.in_(team_row_ids)).all()}
        team_ids = [teams_by_id[tid].canonical_team_id for tid in team_row_ids]
        index_of = {row_id: i for i, row_id in enumerate(team_row_ids)}

        def to_records(rows) -> list[GoalMatchRecord]:
            return [
                GoalMatchRecord(index_of[f.home_team_id], index_of[f.away_team_id], r.home_goals, r.away_goals)
                for f, r in rows
            ]

        train_matches = to_records(train_rows)

        games_played_at_cutoff: dict[str, int] = {tid: 0 for tid in team_ids}
        for f, _ in train_rows:
            games_played_at_cutoff[teams_by_id[f.home_team_id].canonical_team_id] += 1
            games_played_at_cutoff[teams_by_id[f.away_team_id].canonical_team_id] += 1

        candidates: list[CandidateResult] = []
        for model_name, use_dc in CANDIDATES:
            result = self._evaluate_candidate(
                model_name, use_dc, team_ids, train_matches, val_rows, teams_by_id, games_played_at_cutoff
            )
            if result is not None:
                candidates.append(result)

        if not candidates:
            report.skipped_reason = "no candidate model could be evaluated on the holdout split"
            self._clear_weights(competition)
            return report

        # Softmax over negative log-loss: lower held-out loss -> higher weight.
        losses = np.array([c.metrics.mean_log_loss for c in candidates])
        raw = np.exp(-(losses - losses.min()))
        weights = raw / raw.sum()
        for c, w in zip(candidates, weights):
            c.weight = float(w)

        window_start = train_rows[0][0].kickoff_utc
        window_end = val_rows[-1][0].kickoff_utc
        self._persist_weights(competition, candidates, window_start, window_end)

        report.trained = True
        report.candidates = candidates
        return report

    def _evaluate_candidate(
        self, model_name, use_dc, team_ids, train_matches, val_rows, teams_by_id, games_played_at_cutoff
    ) -> CandidateResult | None:
        try:
            model = GoalModel(use_dc_adjustment=use_dc, l2_regularization=self.settings.model_l2_regularization)
            fit = model.fit(team_ids, train_matches)
            if model_name == "hierarchical_model":
                fit = shrink_fit(fit, games_played_at_cutoff, self.settings)

            predictions = []
            actual_indices = []
            for f, r in val_rows:
                home_id = teams_by_id[f.home_team_id].canonical_team_id
                away_id = teams_by_id[f.away_team_id].canonical_team_id
                if home_id not in fit.attack or away_id not in fit.attack:
                    continue  # team never appeared in the training window
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
                predictions.append((outcomes["home_win"], outcomes["draw"], outcomes["away_win"]))
                actual_indices.append(HOME if r.home_goals > r.away_goals else (DRAW if r.home_goals == r.away_goals else AWAY))

            if not predictions:
                return None
            metrics = evaluate_predictions(predictions, actual_indices)
            return CandidateResult(model_name=model_name, metrics=metrics)
        except Exception as exc:  # a single bad candidate must not abort the whole ensemble
            logger.warning("ensemble_candidate_failed", model_name=model_name, error=str(exc))
            return None

    def _persist_weights(self, competition: Competition, candidates: list[CandidateResult], window_start, window_end) -> None:
        self._clear_weights(competition)
        for c in candidates:
            model_version = (
                self.db.query(ModelVersion)
                .filter_by(model_name=c.model_name, competition_id=competition.id, status="ENABLED")
                .order_by(ModelVersion.trained_at.desc())
                .first()
            )
            if model_version is None:
                continue  # candidate scored on the holdout split but has no live production version
            self.db.add(
                ModelWeight(
                    model_version_id=model_version.id,
                    competition_id=competition.id,
                    weight=c.weight,
                    learned_from_window_start=window_start,
                    learned_from_window_end=window_end,
                )
            )
            # Reuses CalibrationResult as the general holdout-validation ledger
            # (section 36) — GET /model-performance reads this back per model.
            record = (
                self.db.query(CalibrationResult)
                .filter_by(model_version_id=model_version.id, competition_id=competition.id, forecast_type="ensemble_validation")
                .first()
            )
            if record is None:
                record = CalibrationResult(
                    model_version_id=model_version.id, competition_id=competition.id, forecast_type="ensemble_validation"
                )
                self.db.add(record)
            record.method = c.model_name
            record.brier_score = c.metrics.mean_brier_score
            record.log_loss = c.metrics.mean_log_loss
            record.ranked_probability_score = c.metrics.mean_rps
            record.evaluated_at = window_end or dt.datetime.now(dt.timezone.utc)
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
