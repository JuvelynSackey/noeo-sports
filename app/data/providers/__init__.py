"""Provider factory — selects the active FootballDataProvider from config.

Section 9 (automatic failover) will extend this into a primary/secondary
chain; for Phase 1 it resolves a single configured provider.
"""
from __future__ import annotations

from app.config import Settings, get_settings
from app.data.providers.base import FootballDataProvider, ProviderError
from app.data.providers.football_data_org import FootballDataOrgProvider
from app.data.providers.mock_provider import MockProvider

__all__ = ["FootballDataProvider", "ProviderError", "get_provider"]


def get_provider(settings: Settings | None = None) -> FootballDataProvider:
    settings = settings or get_settings()

    if settings.data_provider == "mock":
        return MockProvider()

    if settings.data_provider == "football_data_org":
        return FootballDataOrgProvider(
            api_key=settings.football_data_org_api_key or "",
            base_url=settings.football_data_org_base_url,
        )

    raise ProviderError(f"Unknown DATA_PROVIDER '{settings.data_provider}'")
