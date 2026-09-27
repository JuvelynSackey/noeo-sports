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

    # Deployment (Phase 12) — "production" gates the startup safety checks in
    # app/api/main.py (e.g. refusing to boot with the default secret_key).
    environment: str = "development"

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

    # API hardening (Phase 12) — CORS is opt-in (empty = no cross-origin
    # browser access at all, since this API has no first-party frontend of
    # its own); the login rate limit is a single-process, in-memory best
    # effort (see app/services/rate_limiter.py) rather than a distributed
    # one, sized for the common single-instance deployment this project
    # targets.
    cors_allowed_origins: list[str] = []
    login_rate_limit_attempts: int = 10
    login_rate_limit_window_seconds: int = 60

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

    # Walk-forward backtesting (section 35) — the source of out-of-sample
    # predictions for both ensemble weight learning and calibration fitting.
    # Expanding window: train on everything up to a point, predict the next
    # `backtest_fold_size` matches, fold them into training, repeat.
    backtest_initial_train_matches: int = 10
    backtest_fold_size: int = 5

    # Ensemble weight learning (section 34) — how many pooled out-of-sample
    # walk-forward predictions a candidate needs before it's trusted with a
    # nonzero weight at all.
    ensemble_min_validation_matches: int = 5

    # Calibration (section 37). "isotonic" | "platt" | "beta".
    calibration_method: str = "isotonic"
    calibration_min_validation_matches: int = 20

    # Automatic full-sync scheduling (sections 13, 51, 64). Off by default —
    # starting the API must never silently begin making outbound provider
    # calls and writing to the database unless an operator opts in.
    scheduler_enabled: bool = False
    full_sync_interval_hours: int = 6

    # Out-of-distribution detection (section 40) — soft signals that flag a
    # forecast rather than block it; a completely unseen team still hard-fails
    # in ForecastService's quality gate regardless of these.
    ood_expected_goals_zscore_threshold: float = 3.0
    ood_team_strength_zscore_threshold: float = 3.0
    ood_min_snapshots_for_established_team: int = 3
    ood_min_matches_for_established_competition: int = 15
    ood_uncertainty_inflation_factor: float = 1.5

    # Model/data drift detection (section 42) — persisted as ModelMonitoring
    # rows; "breached" triggers a SystemEvent for administrator review
    # (section 49's "consider retraining" signal), never an automatic retrain.
    drift_psi_threshold: float = 0.25
    drift_team_strength_threshold: float = 0.75
    drift_scoring_environment_threshold: float = 0.5
    drift_min_predictions_for_probability_drift: int = 10
    drift_js_divergence_threshold: float = 0.1

    # Champion/challenger deployment gate (section 11's staged-rollout
    # requirement) — dixon_coles/poisson_baseline/hierarchical_model only,
    # the same scope Phase 7 backtesting settled on. A retrain is only
    # promoted over the current champion if it doesn't meaningfully regress
    # on matches completed since the champion's own training window ended;
    # too few of those (a rerun with no new results, or no champion yet)
    # promotes unconditionally, since there's nothing to compare against.
    champion_challenger_min_new_matches: int = 5
    champion_challenger_log_loss_tolerance: float = 0.02


@lru_cache
def get_settings() -> Settings:
    return Settings()
