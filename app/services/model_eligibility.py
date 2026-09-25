"""Model Eligibility Engine — MASTER BUILD PROMPT section 17.

Determines which models can operate for a competition and records *why*
when one can't ("Dixon-Coles: ENABLED" / "xG Model: DISABLED — xG
unavailable"). Only the models implemented so far (Phase 3: Dixon-Coles,
the Poisson baseline, and dynamic team strength) are evaluated here; later
phases add xG/corners/cards/ML entries to this same engine rather than
building a separate one.
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


class ModelEligibilityService:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def evaluate(self, n_matches: int, n_teams: int, match_date_span_days: float) -> EligibilityReport:
        threshold = self.settings.min_matches_for_model_fit

        if n_teams < 2:
            insufficient_teams = EligibilityResult(False, f"fewer than 2 teams with results (n_teams={n_teams})")
            return EligibilityReport(insufficient_teams, insufficient_teams, insufficient_teams)

        if n_matches < threshold:
            reason = f"insufficient completed results ({n_matches} < {threshold})"
            insufficient = EligibilityResult(False, reason)
            return EligibilityReport(insufficient, insufficient, insufficient)

        goal_models_ok = EligibilityResult(True, None)

        min_span = self.settings.min_days_span_for_dynamic_strength
        if match_date_span_days < min_span:
            dynamic = EligibilityResult(
                False, f"match history spans only {match_date_span_days:.0f} days (< {min_span}); no meaningful recency signal"
            )
        else:
            dynamic = EligibilityResult(True, None)

        return EligibilityReport(dixon_coles=goal_models_ok, poisson_baseline=goal_models_ok, dynamic_strength=dynamic)
