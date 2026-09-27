"""Probability calibration — MASTER BUILD PROMPT section 37.

Fits a recalibration map for P(home win) from pooled walk-forward
out-of-sample predictions (`app/services/backtesting.py`, section 35) for
the champion `dixon_coles` model — measuring Brier score, log loss, RPS,
expected calibration error and a reliability curve on the same predictions,
and fitting isotonic regression, Platt scaling, or beta calibration (Kull
et al. 2017) to them, selectable via `settings.calibration_method`. This
superseded Phase 6's original single train/validation split with the more
robust, pooled walk-forward estimate. Skipped entirely — passing raw
probabilities through unchanged — when there aren't enough out-of-sample
predictions to fit a trustworthy calibrator instead of overfitting to a
handful of points.
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
from app.database.models.modeling import CalibrationResult, ModelVersion
from app.evaluation.metrics import HOME
from app.services.backtesting import BacktestReport, BacktestingService

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

    def train(self, competition: Competition, backtest_reports: dict[str, BacktestReport] | None = None) -> CalibrationTrainingReport:
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

        if backtest_reports is not None and "dixon_coles" in backtest_reports:
            backtest = backtest_reports["dixon_coles"]
        else:
            backtest = BacktestingService(self.db, self.settings).run(competition, "dixon_coles", True)

        threshold = self.settings.calibration_min_validation_matches
        if not backtest.completed or len(backtest.predictions) < threshold:
            n = len(backtest.predictions) if backtest.completed else 0
            report.skipped_reason = backtest.skipped_reason or f"only {n} out-of-sample predictions available (< {threshold})"
            return report

        predicted_home_win = [p.predicted_outcome[HOME] for p in backtest.predictions]
        actual_home_win = [p.actual_outcome_index == HOME for p in backtest.predictions]

        method = self.settings.calibration_method
        calibration_map = self._fit_map(method, predicted_home_win, actual_home_win)

        record = (
            self.db.query(CalibrationResult)
            .filter_by(model_version_id=champion.id, competition_id=competition.id, forecast_type="outcome_probabilities")
            .first()
        )
        if record is None:
            record = CalibrationResult(
                model_version_id=champion.id, competition_id=competition.id, forecast_type="outcome_probabilities"
            )
            self.db.add(record)
        record.season_id = None
        record.method = method
        record.brier_score = backtest.metrics.mean_brier_score
        record.log_loss = backtest.metrics.mean_log_loss
        record.ranked_probability_score = backtest.metrics.mean_rps
        record.calibration_error = backtest.calibration_error
        record.reliability_curve = {"points": backtest.reliability_curve}
        record.calibration_map = calibration_map
        record.evaluated_at = dt.datetime.now(dt.timezone.utc)
        self.db.commit()

        report.fitted = True
        report.method = method
        report.n_validation = len(backtest.predictions)
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
