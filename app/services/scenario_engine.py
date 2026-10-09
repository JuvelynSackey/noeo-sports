"""Scenario engine — MASTER BUILD PROMPT section 59.

Every result is labelled `HYPOTHETICAL` and persisted as a `ScenarioPrediction`
pointing at a specific `baseline_prediction_id` — it never mutates or
replaces the official forecast (section 53's immutability guarantee extends
here too), and `forecast_service.py` never reads scenario rows back.

Scope: the model's actual parameter space is per-team attack/defence
strength (on a log scale) and home advantage, so every supported scenario
is expressed as a delta against the fixture's own anchor (`dixon_coles`)
model fit. That's also how a "missing-player" assumption has to be
expressed here — there's no real lineup/injury data source to assign a
specific player's contribution to, and this project never fabricates that
kind of data, so a user-supplied strength delta, clearly labelled
hypothetical, is the honest substitute. Two scenario types from the
spec's own bullet list aren't modelled at all: a data-quality-degradation
assumption and a tactical assumption have no mechanism here that feeds
back into the Dixon-Coles parameter space the way a strength delta does.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.database.models.fixtures import Fixture
from app.database.models.modeling import ModelVersion
from app.database.models.predictions import Prediction, ScenarioPrediction
from app.database.models.teams import Team
from app.forecasting.score_matrix import (
    build_score_matrix,
    expected_goals_from_matrix,
    goal_distribution,
    most_probable_scorelines,
    outcome_probabilities,
)
from app.models.goal_model import GoalModel, GoalModelFit

LABEL = "HYPOTHETICAL"


@dataclass
class ScenarioAssumptions:
    home_advantage_delta: float = 0.0
    attack_delta: dict[str, float] = field(default_factory=dict)
    defence_delta: dict[str, float] = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "home_advantage_delta": self.home_advantage_delta,
            "attack_delta": self.attack_delta,
            "defence_delta": self.defence_delta,
        }


class ScenarioValidationError(ValueError):
    """A controlled-input problem (unknown team, delta out of bounds, no
    baseline to vary) — always a 422 at the API layer, never a 500."""


class ScenarioEngine:
    def __init__(self, db: Session, settings: Settings | None = None) -> None:
        self.db = db
        self.settings = settings or get_settings()

    def run(
        self,
        fixture: Fixture,
        scenario_name: str,
        assumptions: ScenarioAssumptions,
        requested_by: str | None = None,
    ) -> ScenarioPrediction:
        baseline = (
            self.db.query(Prediction)
            .filter_by(fixture_id=fixture.id)
            .order_by(Prediction.predicted_at.desc())
            .first()
        )
        if baseline is None:
            raise ScenarioValidationError("no baseline forecast exists for this fixture; call POST /forecast first")

        champion = self.db.get(ModelVersion, baseline.model_version_id)
        if champion is None or not champion.parameters:
            raise ScenarioValidationError("the baseline forecast's anchor model has no fitted parameters to vary")

        home_team = self.db.get(Team, fixture.home_team_id)
        away_team = self.db.get(Team, fixture.away_team_id)
        home_id, away_id = home_team.canonical_team_id, away_team.canonical_team_id
        allowed_ids = {home_id, away_id}

        for team_id in (*assumptions.attack_delta, *assumptions.defence_delta):
            if team_id not in allowed_ids:
                raise ScenarioValidationError(
                    f"{team_id} is not one of this fixture's teams ({home_id} vs {away_id})"
                )

        max_delta = self.settings.scenario_max_abs_delta
        all_deltas = [assumptions.home_advantage_delta, *assumptions.attack_delta.values(), *assumptions.defence_delta.values()]
        if any(abs(d) > max_delta for d in all_deltas):
            raise ScenarioValidationError(f"every delta must be within +/-{max_delta}")

        fit = GoalModelFit.from_persisted_parameters(champion.parameters, champion.evaluation_metrics or {})
        if home_id not in fit.attack or away_id not in fit.attack:
            raise ScenarioValidationError("one or both teams are not in the anchor model's trained parameters")

        scenario_fit = GoalModelFit(
            team_ids=fit.team_ids,
            attack={**fit.attack, **{t: fit.attack[t] + d for t, d in assumptions.attack_delta.items()}},
            defence={**fit.defence, **{t: fit.defence[t] + d for t, d in assumptions.defence_delta.items()}},
            home_advantage=fit.home_advantage + assumptions.home_advantage_delta,
            rho=fit.rho,
            converged=fit.converged,
            log_likelihood=fit.log_likelihood,
            aic=fit.aic,
            n_matches=fit.n_matches,
            n_params=fit.n_params,
        )

        model = GoalModel(use_dc_adjustment=True, l2_regularization=self.settings.model_l2_regularization)
        score = build_score_matrix(
            model, scenario_fit, home_id, away_id,
            initial_max_goals=self.settings.score_matrix_initial_max_goals,
            tail_threshold=self.settings.score_matrix_tail_threshold,
            max_goals_cap=self.settings.score_matrix_max_goals_cap,
        )
        lam_h, lam_a = expected_goals_from_matrix(score.matrix)
        outcomes = outcome_probabilities(score.matrix)

        scenario_result = {
            "expected_goals_home": lam_h,
            "expected_goals_away": lam_a,
            "outcome_probabilities": outcomes,
            "most_probable_scorelines": most_probable_scorelines(score.matrix, self.settings.most_probable_scorelines_top_n),
            "goal_distribution": goal_distribution(score.matrix),
        }

        baseline_outcomes = baseline.outcome_probabilities or {}
        difference = {
            "expected_goals_home": lam_h - (baseline.expected_goals_home or 0.0),
            "expected_goals_away": lam_a - (baseline.expected_goals_away or 0.0),
            "outcome_probabilities": {k: outcomes[k] - baseline_outcomes.get(k, 0.0) for k in outcomes},
        }

        record = ScenarioPrediction(
            fixture_id=fixture.id,
            baseline_prediction_id=baseline.id,
            scenario_name=scenario_name,
            assumptions=assumptions.as_dict(),
            scenario_result=scenario_result,
            difference=difference,
            requested_by=requested_by,
        )
        self.db.add(record)
        self.db.commit()
        return record
