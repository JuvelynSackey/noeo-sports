"""Provider abstraction — MASTER BUILD PROMPT section 8.

The forecasting/services layer only ever imports `FootballDataProvider`
and the DTOs in `schemas.py`. It must never import a concrete adapter
directly, which is what lets primary/secondary providers be swapped or
fail over (section 9) without touching anything downstream.
"""
from __future__ import annotations

from abc import ABC, abstractmethod

from app.data.providers.schemas import (
    CompetitionDTO,
    FixtureDTO,
    ResultDTO,
    SeasonDTO,
    StatisticDTO,
    TeamDTO,
    XGDTO,
)


class ProviderError(Exception):
    """Raised when a provider cannot fulfil a request (network, auth, rate limit, bad payload)."""


class FootballDataProvider(ABC):
    """Common contract every data source adapter must implement."""

    name: str

    @abstractmethod
    def competitions(self) -> list[CompetitionDTO]:
        """Discover all competitions currently visible to this provider."""

    @abstractmethod
    def seasons(self, competition_id: str) -> list[SeasonDTO]:
        """All seasons known for a competition (past, current, upcoming where available)."""

    @abstractmethod
    def teams(self, competition_id: str, season_id: str) -> list[TeamDTO]:
        """Teams participating in a competition/season."""

    @abstractmethod
    def fixtures(self, competition_id: str, season_id: str) -> list[FixtureDTO]:
        """All fixtures (any status) for a competition/season."""

    @abstractmethod
    def results(self, competition_id: str, season_id: str) -> list[ResultDTO]:
        """Completed-match results for a competition/season."""

    @abstractmethod
    def statistics(self, fixture_id: str) -> list[StatisticDTO]:
        """Match statistics for one fixture, if available."""

    @abstractmethod
    def xg(self, fixture_id: str) -> XGDTO | None:
        """Expected-goals data for one fixture. None if the provider has no xG for it —
        never fabricate a value (MASTER BUILD PROMPT section 20)."""
