"""Central configuration.

All operational knobs (refresh intervals, provider selection, timezone, etc.)
live here and are sourced from environment variables / .env so nothing is
hard-coded per MASTER BUILD PROMPT section 13.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "0.4.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database
    database_url: str = "sqlite:///./football_prediction.db"

    # Provider selection
    data_provider: str = "mock"
    football_data_org_api_key: str | None = None
    football_data_org_base_url: str = "https://api.football-data.org/v4"

    # Display / operational
    admin_timezone: str = "UTC"
    log_level: str = "INFO"

    # Refresh intervals (hours) — configurable, never hard-coded into services
    competition_discovery_interval_hours: int = 24
    fixture_sync_interval_hours: int = 3
    result_sync_interval_hours: int = 6
    data_validation_interval_hours: int = 24
    model_monitoring_interval_hours: int = 24

    # Auth
    secret_key: str = "change-me-in-production"
    access_token_expire_minutes: int = 60

    # Data quality thresholds (section 14/15) — defaults, tunable per deployment
    min_data_quality_for_full_ensemble: float = 0.75
    min_data_quality_for_forecast: float = 0.40

    # Model eligibility / fitting (sections 17, 18, 19, 21)
    min_matches_for_model_fit: int = 10
    min_days_span_for_dynamic_strength: int = 30
    model_l2_regularization: float = 0.01
    recent_form_half_life_days: float = 60.0

    # League baselines (section 16) — hierarchical shrinkage toward a global prior
    # when a competition/season has fewer than this many matches.
    league_shrinkage_min_sample: int = 30
    league_shrinkage_prior_strength: float = 20.0

    # Score matrix / forecast generation (sections 25-30, 61)
    score_matrix_initial_max_goals: int = 10
    score_matrix_tail_threshold: float = 1e-4
    score_matrix_max_goals_cap: int = 25
    most_probable_scorelines_top_n: int = 5
    over_under_lines: list[float] = [0.5, 1.5, 2.5, 3.5, 4.5]

    # Model disagreement thresholds (section 39) — max abs difference in
    # outcome probabilities between the champion and a supporting model.
    model_disagreement_low_threshold: float = 0.05
    model_disagreement_high_threshold: float = 0.15

    # Hierarchical / partial-pooling shrinkage of per-team ratings (section 22).
    # Weight on a team's own raw rating is games_played / (games_played + k) —
    # smaller k than the league-level prior (section 16) because it operates on
    # a single team's own match count, which is naturally much smaller.
    team_shrinkage_prior_strength: float = 6.0

    # Additional markets (sections 20, 31, 32, 33). Corners/cards reuse
    # min_matches_for_model_fit as their eligibility threshold.
    xg_model_min_matches: int = 10
    first_half_model_min_matches: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()
