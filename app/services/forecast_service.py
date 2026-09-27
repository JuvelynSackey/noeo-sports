"""Generates and registers a probabilistic match forecast — MASTER BUILD
PROMPT sections 25-30 (score matrix and everything derived from it), 34
(ensemble blending), 37 (calibration diagnostics), 38-39 (uncertainty /
disagreement), 46-47 (prediction registry and pre-match snapshot) and 61
(the pre-publish quality gate).

`dixon_coles` remains the anchor for the quality gate (convergence, OOD,
leakage, versioning) since it's guaranteed to exist whenever any goal model
does. The actual published score matrix, however, is a weighted blend of
every ENABLED goal-based model with a learned `ModelWeight`
(`app/services/ensemble.py`) — falling back to `dixon_coles` alone when no
weights have been learned yet (e.g. too little data for a holdout split).
Calibration (`app/services/calibration.py`) is surfaced as a diagnostic
comparison — a `calibrated_home_win_probability` alongside the raw ensemble
figure — rather than silently overwriting `outcome_probabilities`, so the
published numbers always stay traceable to one score matrix (section 29).
"""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field

import numpy as np
from sqlalchemy.orm import Session

from app.config import APP_VERSION, Settings, get_settings
from app.database.models.competitions import Competition
from app.database.models.enums import DataQualityStatus, DisagreementLevel, ForecastStatus
from app.database.models.fixtures import Fixture
from app.database.models.modeling import CalibrationResult, ModelVersion, ModelWeight
from app.database.models.predictions import Prediction, PredictionSnapshot
from app.database.models.quality import DataQuality
from app.database.models.teams import Team
from app.forecasting.score_matrix import (
    ScoreMatrixResult,
    btts_and_clean_sheets,
    build_score_matrix,
    check_consistency,
    expected_goals_from_matrix,
    goal_distribution,
    most_probable_scorelines,
    outcome_probabilities,
    over_under_probabilities,
)
from app.logging_config import get_logger
from app.models.goal_model import GoalModel, GoalModelFit
from app.services.calibration import apply_calibration
from app.services.market_models import CARDS_MODEL, CORNERS_MODEL, FIRST_HALF_MODEL
from app.services.model_training import DIXON_COLES

logger = get_logger(__name__)

FEATURE_VERSION = "goal_model_v1"


@dataclass
class ForecastResult:
    prediction_id: str
    fixture_id: int
    forecast_status: ForecastStatus
    validation_report: dict = field(default_factory=dict)
    expected_goals_home: float | None = None
    expected_goals_away: float | None = None
    most_probable_scorelines: list[dict] = field(default_factory=list)
    outcome_probabilities: dict | None = None
    goal_distribution: dict | None = None
    over_under: dict | None = None
    btts_and_clean_sheets: dict | None = None
    aleatoric_uncertainty: float | None = None
    epistemic_uncertainty: float | None = None
    data_quality_score: float | None = None
    model_disagreement_level: str | None = None
    ood_status: bool = False
    champion_model: str | None = None
    supporting_models: list[str] = field(default_factory=list)
    ensemble_weights: dict[str, float] = field(default_factory=dict)
    model_version: str | None = None
    dataset_version: str | None = None
    predicted_at: dt.datetime | None = None
    warnings: list[str] = field(default_factory=list)
    supplementary_markets: dict = field(default_factory=dict)
    calibration: dict | None = None


def _fit_from_model_version(mv: ModelVersion) -> GoalModelFit:
    params = mv.parameters or {}
    metrics = mv.evaluation_metrics or {}
    return GoalModelFit(
        team_ids=params.get("team_ids", []),
        attack=params.get("attack", {}),
        defence=params.get("defence", {}),
        home_advantage=params.get("home_advantage", 0.0),
        rho=params.get("rho", 0.0),
        converged=bool(metrics.get("converged", True)),
        log_likelihood=metrics.get("log_likelihood", 0.0),
        aic=metrics.get("aic", 0.0),
        n_matches=metrics.get("n_matches", 0),
        n_params=metrics.get("n_params", 0),
    )


class ForecastService:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def generate(self, fixture: Fixture) -> ForecastResult:
        result = ForecastResult(
            prediction_id=str(uuid.uuid4()),
            fixture_id=fixture.id,
            forecast_status=ForecastStatus.FAILED_VALIDATION,
            predicted_at=dt.datetime.now(dt.timezone.utc),
        )
        errors: list[str] = []
        warnings: list[str] = []

        competition = self.db.get(Competition, fixture.competition_id)
        home_team = self.db.get(Team, fixture.home_team_id)
        away_team = self.db.get(Team, fixture.away_team_id)

        champion = (
            self.db.query(ModelVersion)
            .filter_by(model_name=DIXON_COLES, competition_id=competition.id, status="ENABLED")
            .order_by(ModelVersion.trained_at.desc())
            .first()
        )
        if champion is None:
            errors.append("no ENABLED dixon_coles model for this competition")
            return self._finalize(result, errors, warnings, None, None)

        result.champion_model = DIXON_COLES
        result.model_version = champion.version
        result.dataset_version = self._dataset_version(champion)

        # --- Quality gate (section 61) ---
        if not champion.parameters:
            errors.append("champion model has no fitted parameters")
        metrics = champion.evaluation_metrics or {}
        if not metrics.get("converged", True):
            errors.append("champion model did not converge")

        if fixture.kickoff_utc and champion.training_window_end:
            kickoff = fixture.kickoff_utc
            window_end = champion.training_window_end
            if kickoff.tzinfo is None:
                kickoff = kickoff.replace(tzinfo=dt.timezone.utc)
            if window_end.tzinfo is None:
                window_end = window_end.replace(tzinfo=dt.timezone.utc)
            if kickoff <= window_end:
                errors.append(
                    f"potential leakage: fixture kickoff ({kickoff.isoformat()}) is not after the "
                    f"model's training window end ({window_end.isoformat()})"
                )

        data_quality = (
            self.db.query(DataQuality)
            .filter_by(competition_id=competition.id, season_id=fixture.season_id)
            .order_by(DataQuality.evaluated_at.desc())
            .first()
        )
        if data_quality is not None:
            result.data_quality_score = data_quality.overall_score
            if data_quality.status == DataQualityStatus.INSUFFICIENT:
                errors.append(f"competition data quality is INSUFFICIENT (score={data_quality.overall_score:.2f})")
            elif data_quality.status == DataQualityStatus.LIMITED:
                warnings.append(f"competition data quality is LIMITED (score={data_quality.overall_score:.2f})")

        home_id, away_id = home_team.canonical_team_id if home_team else None, away_team.canonical_team_id if away_team else None
        fit = _fit_from_model_version(champion)
        if home_id not in fit.attack or away_id not in fit.attack:
            result.ood_status = True
            errors.append(
                f"team not present in the trained model (home={home_id in fit.attack}, away={away_id in fit.attack})"
            )

        if errors:
            return self._finalize(result, errors, warnings, champion, None)

        # --- Ensemble score matrix (section 34) and everything derived from it ---
        score, ensemble_weights, disagreement = self._build_ensemble_score(competition, home_id, away_id, fit, warnings)
        result.ensemble_weights = ensemble_weights
        result.supporting_models = [name for name in ensemble_weights if name != DIXON_COLES]
        result.model_disagreement_level = disagreement

        lam_h, lam_a = expected_goals_from_matrix(score.matrix)
        outcomes = outcome_probabilities(score.matrix)
        distribution = goal_distribution(score.matrix)
        over_under = over_under_probabilities(score.matrix, self.settings.over_under_lines)
        btts = btts_and_clean_sheets(score.matrix)
        scorelines = most_probable_scorelines(score.matrix, self.settings.most_probable_scorelines_top_n)

        consistency = check_consistency(score.matrix, outcomes, over_under)
        if not consistency.consistent:
            errors.extend(f"consistency check failed: {v}" for v in consistency.violations)
            return self._finalize(result, errors, warnings, champion, fit)

        if score.tail_probability > self.settings.score_matrix_tail_threshold:
            warnings.append(
                f"score matrix truncated at {score.max_goals} goals with residual tail probability "
                f"{score.tail_probability:.6f}"
            )

        result.expected_goals_home = lam_h
        result.expected_goals_away = lam_a
        result.outcome_probabilities = outcomes
        result.goal_distribution = distribution
        result.over_under = over_under
        result.btts_and_clean_sheets = btts
        result.most_probable_scorelines = scorelines
        result.aleatoric_uncertainty = (lam_h + lam_a) ** 0.5  # intrinsic scoring randomness (Poisson-scale proxy)
        result.epistemic_uncertainty = self._epistemic_uncertainty(champion, home_id, away_id)

        result.calibration = self._calibration_diagnostic(champion, outcomes)

        if data_quality is None:
            warnings.append("no data-quality record found for this competition/season")

        forecast_status = ForecastStatus.ACTIVE
        if data_quality is not None and data_quality.status == DataQualityStatus.LIMITED:
            forecast_status = ForecastStatus.LIMITED
        if len(ensemble_weights) < 2:
            forecast_status = ForecastStatus.LIMITED  # no cross-model ensemble to corroborate the forecast

        # --- Additional markets (sections 31-33) — independently eligible,
        # non-blocking: an unavailable one is just missing from the output,
        # never a reason to fail the main goals-based forecast.
        supplementary: dict = {}
        first_half = self._first_half_market(competition, home_id, away_id, warnings)
        if first_half is not None:
            supplementary["first_half"] = first_half
        corners = self._rate_market(competition, home_id, away_id, CORNERS_MODEL, warnings)
        if corners is not None:
            supplementary["corners"] = corners
        cards = self._rate_market(competition, home_id, away_id, CARDS_MODEL, warnings)
        if cards is not None:
            supplementary["cards"] = cards
        result.supplementary_markets = supplementary

        return self._finalize(result, errors, warnings, champion, fit, forecast_status, score, home_team, away_team)

    def _latest_enabled(self, competition: Competition, model_name: str) -> ModelVersion | None:
        return (
            self.db.query(ModelVersion)
            .filter_by(model_name=model_name, competition_id=competition.id, status="ENABLED")
            .order_by(ModelVersion.trained_at.desc())
            .first()
        )

    def _first_half_market(self, competition: Competition, home_id: str, away_id: str, warnings: list[str]) -> dict | None:
        mv = self._latest_enabled(competition, FIRST_HALF_MODEL)
        if mv is None:
            warnings.append(f"{FIRST_HALF_MODEL} unavailable for this competition")
            return None
        fit = _fit_from_model_version(mv)
        if home_id not in fit.attack or away_id not in fit.attack:
            warnings.append(f"{FIRST_HALF_MODEL} unavailable for these teams (not in its training data)")
            return None

        model = GoalModel(use_dc_adjustment=True)
        score = build_score_matrix(
            model,
            fit,
            home_id,
            away_id,
            initial_max_goals=self.settings.score_matrix_initial_max_goals,
            tail_threshold=self.settings.score_matrix_tail_threshold,
            max_goals_cap=self.settings.score_matrix_max_goals_cap,
        )
        lam_h, lam_a = model.expected_goals(fit, home_id, away_id)
        top = most_probable_scorelines(score.matrix, top_n=1)[0]
        return {
            "expected_goals_home": lam_h,
            "expected_goals_away": lam_a,
            "expected_goals_total": lam_h + lam_a,
            "most_probable_score": top,
        }

    def _rate_market(self, competition: Competition, home_id: str, away_id: str, model_name: str, warnings: list[str]) -> dict | None:
        mv = self._latest_enabled(competition, model_name)
        if mv is None:
            warnings.append(f"{model_name} unavailable for this competition")
            return None
        fit = _fit_from_model_version(mv)
        if home_id not in fit.attack or away_id not in fit.attack:
            warnings.append(f"{model_name} unavailable for these teams (not in its training data)")
            return None

        model = GoalModel(use_dc_adjustment=False)
        lam_h, lam_a = model.expected_goals(fit, home_id, away_id)
        return {"expected_home": lam_h, "expected_away": lam_a, "expected_total": lam_h + lam_a}

    def _build_ensemble_score(
        self, competition: Competition, home_id: str, away_id: str, champion_fit: GoalModelFit, warnings: list[str]
    ) -> tuple[ScoreMatrixResult, dict[str, float], str | None]:
        """Blends every ENABLED goal-based model with a learned `ModelWeight`
        into one score matrix (linear pooling of each member's normalized
        distribution), falling back to `dixon_coles` alone when no weights
        have been learned yet. Also returns the LOW/MEDIUM/HIGH disagreement
        across whichever members were actually used (section 39)."""
        weight_rows = (
            self.db.query(ModelWeight, ModelVersion)
            .join(ModelVersion, ModelWeight.model_version_id == ModelVersion.id)
            .filter(ModelWeight.competition_id == competition.id, ModelVersion.status == "ENABLED")
            .all()
        )

        def _single_model_fallback(reason: str) -> tuple[ScoreMatrixResult, dict[str, float], str | None]:
            warnings.append(reason)
            model = GoalModel(use_dc_adjustment=True)
            score = build_score_matrix(
                model,
                champion_fit,
                home_id,
                away_id,
                initial_max_goals=self.settings.score_matrix_initial_max_goals,
                tail_threshold=self.settings.score_matrix_tail_threshold,
                max_goals_cap=self.settings.score_matrix_max_goals_cap,
            )
            return score, {DIXON_COLES: 1.0}, None

        if not weight_rows:
            return _single_model_fallback("ensemble weights unavailable for this competition; using dixon_coles alone")

        members = []  # (model_name, weight, fit, use_dc)
        for weight_row, model_version in weight_rows:
            fit = _fit_from_model_version(model_version)
            if home_id not in fit.attack or away_id not in fit.attack:
                warnings.append(f"{model_version.model_name} excluded from the ensemble (team not in its training data)")
                continue
            use_dc = bool((model_version.hyperparameters or {}).get("use_dc_adjustment", False))
            members.append((model_version.model_name, weight_row.weight, fit, use_dc))

        if not members:
            return _single_model_fallback("every ensemble member excluded (OOD teams); using dixon_coles alone")

        per_member = []
        max_goals_needed = self.settings.score_matrix_initial_max_goals
        outcomes_by_member: dict[str, tuple[float, float, float]] = {}
        for name, weight, fit, use_dc in members:
            model = GoalModel(use_dc_adjustment=use_dc)
            member_score = build_score_matrix(
                model,
                fit,
                home_id,
                away_id,
                initial_max_goals=self.settings.score_matrix_initial_max_goals,
                tail_threshold=self.settings.score_matrix_tail_threshold,
                max_goals_cap=self.settings.score_matrix_max_goals_cap,
            )
            max_goals_needed = max(max_goals_needed, member_score.max_goals)
            member_outcomes = outcome_probabilities(member_score.matrix)
            outcomes_by_member[name] = (member_outcomes["home_win"], member_outcomes["draw"], member_outcomes["away_win"])
            per_member.append((name, weight, model, fit))

        total_weight = sum(w for _, w, _, _ in per_member)
        blended = np.zeros((max_goals_needed + 1, max_goals_needed + 1))
        max_tail = 0.0
        ensemble_weights: dict[str, float] = {}
        for name, weight, model, fit in per_member:
            raw = model.score_matrix(fit, home_id, away_id, max_goals=max_goals_needed)
            total = float(raw.sum())
            normalized = raw / total if total > 0 else raw
            normalized_weight = weight / total_weight
            blended += normalized_weight * normalized
            max_tail = max(max_tail, max(1.0 - total, 0.0))
            ensemble_weights[name] = normalized_weight

        blended_total = float(blended.sum())
        blended = blended / blended_total if blended_total > 0 else blended

        disagreement = None
        if len(outcomes_by_member) >= 2:
            values = list(outcomes_by_member.values())
            max_diff = max(
                abs(a[i] - b[i]) for idx_a, a in enumerate(values) for b in values[idx_a + 1 :] for i in range(3)
            )
            if max_diff < self.settings.model_disagreement_low_threshold:
                disagreement = DisagreementLevel.LOW.value
            elif max_diff < self.settings.model_disagreement_high_threshold:
                disagreement = DisagreementLevel.MEDIUM.value
            else:
                disagreement = DisagreementLevel.HIGH.value

        return ScoreMatrixResult(matrix=blended, max_goals=max_goals_needed, tail_probability=max_tail), ensemble_weights, disagreement

    def _calibration_diagnostic(self, champion: ModelVersion, outcomes: dict[str, float]) -> dict | None:
        record = (
            self.db.query(CalibrationResult)
            .filter_by(model_version_id=champion.id, competition_id=champion.competition_id, forecast_type="outcome_probabilities")
            .order_by(CalibrationResult.evaluated_at.desc())
            .first()
        )
        if record is None or not record.calibration_map:
            return None
        calibrated_home_win = apply_calibration(record.calibration_map, outcomes["home_win"])
        return {
            "method": record.method,
            "raw_home_win_probability": outcomes["home_win"],
            "calibrated_home_win_probability": calibrated_home_win,
            "calibration_error": record.calibration_error,
            "brier_score": record.brier_score,
            "log_loss": record.log_loss,
        }

    def _epistemic_uncertainty(self, model_version: ModelVersion, home_id: str, away_id: str) -> float | None:
        # Standard errors aren't persisted on ModelVersion itself (only used
        # transiently to populate TeamStrength.uncertainty); fall back to None
        # rather than fabricating a number when they're unavailable.
        from app.database.models.league import TeamStrength

        rows = (
            self.db.query(TeamStrength)
            .join(Team, TeamStrength.team_id == Team.id)
            .filter(Team.canonical_team_id.in_([home_id, away_id]), TeamStrength.competition_id == model_version.competition_id)
            .order_by(TeamStrength.as_of.desc())
            .all()
        )
        uncertainties = [r.uncertainty for r in rows if r.uncertainty is not None]
        if not uncertainties:
            return None
        return sum(uncertainties) / len(uncertainties)

    def _dataset_version(self, model_version: ModelVersion) -> str:
        metrics = model_version.evaluation_metrics or {}
        end = model_version.training_window_end.isoformat() if model_version.training_window_end else "unknown"
        return f"{metrics.get('n_matches', 0)}matches@{end}"

    def _finalize(
        self,
        result: ForecastResult,
        errors: list[str],
        warnings: list[str],
        champion: ModelVersion | None,
        fit: GoalModelFit | None,
        forecast_status: ForecastStatus | None = None,
        score=None,
        home_team: Team | None = None,
        away_team: Team | None = None,
    ) -> ForecastResult:
        result.warnings = warnings
        if errors:
            result.forecast_status = ForecastStatus.FAILED_VALIDATION
        else:
            result.forecast_status = forecast_status or ForecastStatus.FAILED_VALIDATION

        result.validation_report = {
            "errors": errors,
            "warnings": warnings,
            "ensemble_weights": result.ensemble_weights,
            "calibration": result.calibration,
        }

        prediction = Prediction(
            prediction_id=result.prediction_id,
            fixture_id=result.fixture_id,
            predicted_at=result.predicted_at,
            model_version_id=champion.id if champion else None,
            dataset_version=result.dataset_version or "unknown",
            feature_version=FEATURE_VERSION,
            software_version=APP_VERSION,
            score_matrix=(
                {"matrix": score.matrix.tolist(), "max_goals": score.max_goals, "tail_probability": score.tail_probability}
                if score is not None
                else {}
            ),
            expected_goals_home=result.expected_goals_home,
            expected_goals_away=result.expected_goals_away,
            outcome_probabilities=result.outcome_probabilities or {},
            goal_distribution={
                **(result.goal_distribution or {}),
                "over_under": result.over_under or {},
                **(result.btts_and_clean_sheets or {}),
            }
            if result.goal_distribution
            else None,
            forecast_status=result.forecast_status,
            validation_report=result.validation_report,
            aleatoric_uncertainty=result.aleatoric_uncertainty,
            epistemic_uncertainty=result.epistemic_uncertainty,
            data_quality_score=result.data_quality_score,
            model_disagreement_level=result.model_disagreement_level,
            ood_status=result.ood_status,
            supplementary_markets=result.supplementary_markets or None,
        )

        # model_version_id is NOT NULL in the schema; a forecast that fails
        # before any model is found cannot be registered as a normal row —
        # log it as a system event instead of writing a broken record.
        if champion is None:
            logger.error("forecast_failed_no_model", fixture_id=result.fixture_id, errors=errors)
            return result

        self.db.add(prediction)
        self.db.flush()

        involved_ids = [t.canonical_team_id for t in (home_team, away_team) if t is not None]
        features = {
            "attack": {tid: fit.attack.get(tid) for tid in involved_ids} if fit else {},
            "defence": {tid: fit.defence.get(tid) for tid in involved_ids} if fit else {},
            "home_advantage": fit.home_advantage if fit else None,
            "rho": fit.rho if fit else None,
        }
        self.db.add(
            PredictionSnapshot(
                prediction_id=prediction.id,
                data_snapshot={
                    "home_team": home_team.canonical_team_id if home_team else None,
                    "away_team": away_team.canonical_team_id if away_team else None,
                    "model_version": champion.version,
                    "n_matches_trained_on": (champion.evaluation_metrics or {}).get("n_matches"),
                },
                features=features,
                model_configuration=champion.hyperparameters or {},
                snapshot_taken_at=result.predicted_at,
            )
        )
        self.db.commit()
        return result
