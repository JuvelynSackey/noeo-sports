"""Central configuration.

All operational knobs (refresh intervals, provider selection, timezone, etc.)
live here and are sourced from environment variables / .env so nothing is
hard-coded per MASTER BUILD PROMPT section 13.
"""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    return Settings()
