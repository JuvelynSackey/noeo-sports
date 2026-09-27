"""Probability calibration — MASTER BUILD PROMPT section 37.

Fits a recalibration map for P(home win) using the same chronological
holdout split idea as ensemble weight learning (`app/services/ensemble.py`):
the earliest matches train the champion model, the most recent ones are
used both to measure calibration (Brier score, log loss, RPS, expected
calibration error, a reliability curve) and to fit the correction itself.
Supports isotonic regression, Platt scaling, and beta calibration (Kull et
al. 2017) — selectable via `settings.calibration_method`. Skipped entirely,
passing raw probabilities through unchanged, when there aren't enough
held-out matches to fit a trustworthy calibrator instead of overfitting to
a handful of points.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.models.competitions import Competition
from app.database.models.enums import FixtureStatus
from app.database.models.fixtures import Fixture, Result
from app.database.models.modeling import CalibrationResult, ModelVersion
from app.database.models.teams import Team
from app.evaluation.metrics import AWAY, DRAW, HOME, evaluate_predictions, expected_calibration_error, reliability_curve
from app.forecasting.score_matrix import build_score_matrix, outcome_probabilities
from app.logging_config import get_logger
from app.models.goal_model import GoalMatchRecord, GoalModel

logger = get_logger(__name__)

EPS = 1e-6


@dataclass
class CalibrationTrainingReport:
    competition_canonical_id: str
    fitted: bool
    method: str | None = None
    n_validation: int = 0
    skipped_reason: str | None = None


class CalibrationService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def train(self, competition: Competition) -> CalibrationTrainingReport:
        report = CalibrationTrainingReport(competition_canonical_id=competition.canonical_competition_id, fitted=False)

        champion = (
            self.db.query(ModelVersion)
            .filter_by(model_name="dixon_coles", competition_id=competition.id, status="ENABLED")
            .order_by(ModelVersion.trained_at.desc())
            .first()
        )
        if champion is None:
            report.skipped_reason = "no ENABLED dixon_coles model to calibrate"
            return report

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

        threshold = self.settings.calibration_min_validation_matches
        val_size = max(int(round(len(completed) * self.settings.ensemble_validation_fraction)), threshold)
        train_size = len(completed) - val_size
        if train_size < self.settings.ensemble_min_train_matches or val_size < threshold:
            report.skipped_reason = (
                f"insufficient validation matches to fit calibration ({len(completed)} completed, "
                f"need >= {threshold} held out)"
            )
            return report

        train_rows = completed[:train_size]
        val_rows = completed[train_size:]

        team_row_ids = sorted({f.home_team_id for f, _ in completed} | {f.away_team_id for f, _ in completed})
        teams_by_id = {t.id: t for t in self.db.query(Team).filter(Team.id.in_(team_row_ids)).all()}
        team_ids = [teams_by_id[tid].canonical_team_id for tid in team_row_ids]
        index_of = {row_id: i for i, row_id in enumerate(team_row_ids)}
        train_matches = [
            GoalMatchRecord(index_of[f.home_team_id], index_of[f.away_team_id], r.home_goals, r.away_goals)
            for f, r in train_rows
        ]

        model = GoalModel(use_dc_adjustment=True, l2_regularization=self.settings.model_l2_regularization)
        fit = model.fit(team_ids, train_matches)

        predicted_home_win: list[float] = []
        actual_home_win: list[bool] = []
        predictions: list[tuple[float, float, float]] = []
        actual_indices: list[int] = []
        for f, r in val_rows:
            home_id = teams_by_id[f.home_team_id].canonical_team_id
            away_id = teams_by_id[f.away_team_id].canonical_team_id
            if home_id not in fit.attack or away_id not in fit.attack:
                continue
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
            predicted_home_win.append(outcomes["home_win"])
            actual_home_win.append(r.home_goals > r.away_goals)
            predictions.append((outcomes["home_win"], outcomes["draw"], outcomes["away_win"]))
            actual_indices.append(HOME if r.home_goals > r.away_goals else (DRAW if r.home_goals == r.away_goals else AWAY))

        if len(predicted_home_win) < threshold:
            report.skipped_reason = f"only {len(predicted_home_win)} scoreable validation matches (< {threshold})"
            return report

        method = self.settings.calibration_method
        calibration_map = self._fit_map(method, predicted_home_win, actual_home_win)

        metrics = evaluate_predictions(predictions, actual_indices)
        ece = expected_calibration_error(predicted_home_win, actual_home_win)
        curve = reliability_curve(predicted_home_win, actual_home_win)

        record = (
            self.db.query(CalibrationResult)
            .filter_by(competition_id=competition.id, model_version_id=champion.id, forecast_type="outcome_probabilities")
            .first()
        )
        if record is None:
            record = CalibrationResult(
                competition_id=competition.id, model_version_id=champion.id, forecast_type="outcome_probabilities"
            )
            self.db.add(record)
        record.season_id = val_rows[-1][0].season_id
        record.method = method
        record.brier_score = metrics.mean_brier_score
        record.log_loss = metrics.mean_log_loss
        record.ranked_probability_score = metrics.mean_rps
        record.calibration_error = ece
        record.reliability_curve = {"points": curve}
        record.calibration_map = calibration_map
        record.evaluated_at = dt.datetime.now(dt.timezone.utc)
        self.db.commit()

        report.fitted = True
        report.method = method
        report.n_validation = len(predicted_home_win)
        return report

    def _fit_map(self, method: str, predicted: list[float], actual: list[bool]) -> dict:
        x = np.array(predicted)
        y = np.array([1.0 if a else 0.0 for a in actual])

        if method == "isotonic":
            iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
            iso.fit(x, y)
            return {"method": "isotonic", "x": iso.X_thresholds_.tolist(), "y": iso.y_thresholds_.tolist()}

        if method == "platt":
            lr = LogisticRegression()
            lr.fit(x.reshape(-1, 1), y)
            return {"method": "platt", "coef": float(lr.coef_[0][0]), "intercept": float(lr.intercept_[0])}

        if method == "beta":
            # Beta calibration (Kull, Filho & Flach 2017): logit(p_cal) = a*log(p) +
            # b*log(1-p) + c, fit via logistic regression on the two log-odds features.
            clipped = np.clip(x, EPS, 1 - EPS)
            features = np.column_stack([np.log(clipped), np.log(1 - clipped)])
            lr = LogisticRegression()
            lr.fit(features, y)
            return {"method": "beta", "a": float(lr.coef_[0][0]), "b": float(lr.coef_[0][1]), "c": float(lr.intercept_[0])}

        raise ValueError(f"unknown calibration method: {method}")


def apply_calibration(calibration_map: dict, raw_probability: float) -> float:
    """Reapplies a previously-fitted calibration map to a fresh probability."""
    method = calibration_map.get("method")
    p = min(max(raw_probability, EPS), 1 - EPS)

    if method == "isotonic":
        return float(np.interp(p, calibration_map["x"], calibration_map["y"]))

    if method == "platt":
        z = calibration_map["coef"] * p + calibration_map["intercept"]
        return float(1.0 / (1.0 + math.exp(-z)))

    if method == "beta":
        z = calibration_map["a"] * math.log(p) + calibration_map["b"] * math.log(1 - p) + calibration_map["c"]
        return float(1.0 / (1.0 + math.exp(-z)))

    return raw_probability
