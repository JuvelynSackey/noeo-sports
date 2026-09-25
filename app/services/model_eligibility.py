"""Model Eligibility Engine — MASTER BUILD PROMPT section 17.

The single place that decides which models can run for a competition and
records *why not* when one can't ("Dixon-Coles: ENABLED" / "xG Model:
DISABLED — xG unavailable"). `evaluate()` covers the goal-based models
(Dixon-Coles, Poisson baseline, dynamic strength, and the hierarchical
shrinkage that rides on the same fit); `evaluate_market()` is the same
sample-size/team-count logic generalized for the independent markets added
in Phase 5 (xG, first-half, corners, cards) so every model's eligibility
reason is generated in one place rather than re-implemented per training
service.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.config import Settings, get_settings


@dataclass(frozen=True)
class EligibilityResult:
    eligible: bool
    reason: str | None


@dataclass(frozen=True)
class EligibilityReport:
    dixon_coles: EligibilityResult
    poisson_baseline: EligibilityResult
    dynamic_strength: EligibilityResult
    hierarchical_model: EligibilityResult


class ModelEligibilityService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def evaluate(self, n_matches: int, n_teams: int, match_date_span_days: float) -> EligibilityReport:
        threshold = self.settings.min_matches_for_model_fit

        if n_teams < 2:
            insufficient_teams = EligibilityResult(False, f"fewer than 2 teams with results (n_teams={n_teams})")
            return EligibilityReport(insufficient_teams, insufficient_teams, insufficient_teams, insufficient_teams)

        if n_matches < threshold:
            reason = f"insufficient completed results ({n_matches} < {threshold})"
            insufficient = EligibilityResult(False, reason)
            return EligibilityReport(insufficient, insufficient, insufficient, insufficient)

        goal_models_ok = EligibilityResult(True, None)

        min_span = self.settings.min_days_span_for_dynamic_strength
        if match_date_span_days < min_span:
            dynamic = EligibilityResult(
                False, f"match history spans only {match_date_span_days:.0f} days (< {min_span}); no meaningful recency signal"
            )
        else:
            dynamic = EligibilityResult(True, None)

        return EligibilityReport(
            dixon_coles=goal_models_ok,
            poisson_baseline=goal_models_ok,
            dynamic_strength=dynamic,
            hierarchical_model=goal_models_ok,  # rides on the same fit as dixon_coles
        )

    def evaluate_market(self, n_matches: int, n_teams: int, market_label: str, threshold: int | None = None) -> EligibilityResult:
        """Generic sample-size gate for an independent market (xG, first-half,
        corners, cards) that has its own data availability separate from the
        main goals dataset."""
        threshold = threshold if threshold is not None else self.settings.min_matches_for_model_fit
        if n_teams < 2:
            return EligibilityResult(False, f"fewer than 2 teams with {market_label} data (n_teams={n_teams})")
        if n_matches < threshold:
            return EligibilityResult(False, f"insufficient {market_label} data ({n_matches} < {threshold})")
        return EligibilityResult(True, None)
