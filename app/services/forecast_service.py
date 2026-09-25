"""Generates and registers a probabilistic match forecast — MASTER BUILD
PROMPT sections 25-30 (score matrix and everything derived from it), 38-39
(uncertainty / disagreement, first pass), 46-47 (prediction registry and
pre-match snapshot) and 61 (the pre-publish quality gate).

Uses the competition's currently ENABLED `dixon_coles` ModelVersion as the
champion model; `poisson_baseline`, if also enabled, is a supporting model
used only to compute a first-pass disagreement signal. Full ensemble
weighting and calibration are Phase 6.
"""
from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import APP_VERSION, Settings, get_settings
from app.database.models.competitions import Competition
from app.database.models.enums import DataQualityStatus, DisagreementLevel, ForecastStatus
from app.database.models.fixtures import Fixture
from app.database.models.modeling import ModelVersion
from app.database.models.predictions import Prediction, PredictionSnapshot
from app.database.models.quality import DataQuality
from app.database.models.teams import Team
from app.forecasting.score_matrix import (
    btts_and_clean_sheets,
    build_score_matrix,
    check_consistency,
    goal_distribution,
    most_probable_scorelines,
    outcome_probabilities,
    over_under_probabilities,
)
from app.logging_config import get_logger
from app.models.goal_model import GoalModel, GoalModelFit
from app.services.market_models import CARDS_MODEL, CORNERS_MODEL, FIRST_HALF_MODEL
from app.services.model_training import DIXON_COLES, POISSON_BASELINE

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
    model_version: str | None = None
    dataset_version: str | None = None
    predicted_at: dt.datetime | None = None
    warnings: list[str] = field(default_factory=list)
    supplementary_markets: dict = field(default_factory=dict)


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

        supporting = (
            self.db.query(ModelVersion)
            .filter_by(model_name=POISSON_BASELINE, competition_id=competition.id, status="ENABLED")
            .order_by(ModelVersion.trained_at.desc())
            .first()
        )
        if supporting is not None:
            result.supporting_models.append(POISSON_BASELINE)

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

        # --- Score matrix and every quantity derived from it ---
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

        if supporting is not None:
            result.model_disagreement_level = self._disagreement(fit, champion, supporting, home_id, away_id, outcomes)
        else:
            warnings.append("no supporting model available for disagreement estimate")

        if data_quality is None:
            warnings.append("no data-quality record found for this competition/season")

        forecast_status = ForecastStatus.ACTIVE
        if data_quality is not None and data_quality.status == DataQualityStatus.LIMITED:
            forecast_status = ForecastStatus.LIMITED
        if not result.supporting_models:
            forecast_status = ForecastStatus.LIMITED  # no cross-model disagreement signal yet

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

    def _disagreement(self, champion_fit, champion_mv, supporting_mv, home_id, away_id, champion_outcomes) -> str:
        supporting_fit = _fit_from_model_version(supporting_mv)
        supporting_model = GoalModel(use_dc_adjustment=False)
        supporting_score = build_score_matrix(supporting_model, supporting_fit, home_id, away_id)
        supporting_outcomes = outcome_probabilities(supporting_score.matrix)

        max_diff = max(abs(champion_outcomes[k] - supporting_outcomes[k]) for k in champion_outcomes)
        if max_diff < self.settings.model_disagreement_low_threshold:
            return DisagreementLevel.LOW.value
        if max_diff < self.settings.model_disagreement_high_threshold:
            return DisagreementLevel.MEDIUM.value
        return DisagreementLevel.HIGH.value

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

        result.validation_report = {"errors": errors, "warnings": warnings}

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
