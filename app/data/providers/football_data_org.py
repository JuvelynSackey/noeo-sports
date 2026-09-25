"""Adapter for football-data.org (https://www.football-data.org/documentation/api).

Free-tier scope covers competitions, seasons, teams and fixtures/results for
top European leagues/cups. It does not expose granular match statistics or
xG, so `statistics()` returns an empty list and `xg()` returns None — those
signals are reported as unavailable rather than fabricated (section 20),
and the model-eligibility engine (section 17) is expected to disable any
model that depends on them for this provider.
"""
from __future__ import annotations

import datetime as dt
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.data.providers.base import FootballDataProvider, ProviderError
from app.data.providers.schemas import (
    CompetitionDTO,
    FixtureDTO,
    ResultDTO,
    SeasonDTO,
    StatisticDTO,
    TeamDTO,
    XGDTO,
)
from app.logging_config import get_logger

logger = get_logger(__name__)

_STATUS_MAP = {
    "SCHEDULED": "SCHEDULED",
    "TIMED": "SCHEDULED",
    "IN_PLAY": "IN_PLAY",
    "PAUSED": "IN_PLAY",
    "FINISHED": "COMPLETED",
    "POSTPONED": "POSTPONED",
    "SUSPENDED": "POSTPONED",
    "CANCELLED": "CANCELLED",
    "AWARDED": "COMPLETED",
}

_TYPE_MAP = {
    "LEAGUE": "DOMESTIC_LEAGUE",
    "CUP": "CUP",
}


class RetryableProviderError(ProviderError):
    """Transient failure (network/5xx/429) — safe to retry."""


class FootballDataOrgProvider(FootballDataProvider):
    name = "football_data_org"

    def __init__(self, api_key: str, base_url: str, timeout: float = 15.0) -> None:
        if not api_key:
            raise ProviderError("FOOTBALL_DATA_ORG_API_KEY is not configured")
        self._client = httpx.Client(
            base_url=base_url,
            headers={"X-Auth-Token": api_key},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    @retry(
        retry=retry_if_exception_type(RetryableProviderError),
        stop=stop_after_attempt(4),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        reraise=True,
    )
    def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        try:
            response = self._client.get(path, params=params)
        except httpx.TransportError as exc:
            raise RetryableProviderError(f"transport error calling {path}: {exc}") from exc

        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "unknown")
            logger.warning("provider_rate_limited", path=path, retry_after=retry_after)
            raise RetryableProviderError(f"rate limited on {path}, retry-after={retry_after}")
        if response.status_code >= 500:
            raise RetryableProviderError(f"{response.status_code} from {path}")
        if response.status_code >= 400:
            raise ProviderError(f"{response.status_code} from {path}: {response.text[:500]}")

        return response.json()

    def _provenance(self, source_record_id: str, raw: dict[str, Any]) -> dict[str, Any]:
        return {
            "source_provider": self.name,
            "source_record_id": source_record_id,
            "retrieved_at": dt.datetime.now(dt.timezone.utc),
            "raw_payload": raw,
        }

    def competitions(self) -> list[CompetitionDTO]:
        payload = self._get("/competitions")
        results: list[CompetitionDTO] = []
        for item in payload.get("competitions", []):
            current_season = item.get("currentSeason") or {}
            season_id = None
            if current_season.get("startDate"):
                season_id = str(dt.date.fromisoformat(current_season["startDate"]).year)
            results.append(
                CompetitionDTO(
                    competition_id=str(item["id"]),
                    competition_name=item.get("name", "Unknown"),
                    country=(item.get("area") or {}).get("name"),
                    region=(item.get("area") or {}).get("name"),
                    competition_type=_TYPE_MAP.get(item.get("type", ""), "UNKNOWN"),
                    division_level=None,
                    season_id=season_id,
                    season_name=current_season.get("startDate"),
                    start_date=_parse_date(current_season.get("startDate")),
                    end_date=_parse_date(current_season.get("endDate")),
                    status="ACTIVE" if current_season else "UNKNOWN",
                    number_of_teams=current_season.get("numberOfAvailableTeams") or item.get("numberOfTeams"),
                    competition_format="UNKNOWN",
                    **self._provenance(str(item["id"]), item),
                )
            )
        return results

    def seasons(self, competition_id: str) -> list[SeasonDTO]:
        payload = self._get(f"/competitions/{competition_id}")
        results: list[SeasonDTO] = []
        for season in payload.get("seasons", []):
            start = season.get("startDate")
            season_id = str(dt.date.fromisoformat(start).year) if start else str(season["id"])
            results.append(
                SeasonDTO(
                    competition_id=str(competition_id),
                    season_id=season_id,
                    name=season_id,
                    start_date=_parse_date(season.get("startDate")),
                    end_date=_parse_date(season.get("endDate")),
                    status=_infer_season_status(season.get("startDate"), season.get("endDate")),
                    current_matchday=season.get("currentMatchday"),
                    **self._provenance(str(season["id"]), season),
                )
            )
        return results

    def teams(self, competition_id: str, season_id: str) -> list[TeamDTO]:
        payload = self._get(f"/competitions/{competition_id}/teams", params={"season": season_id})
        results: list[TeamDTO] = []
        for item in payload.get("teams", []):
            results.append(
                TeamDTO(
                    team_id=str(item["id"]),
                    name=item.get("name", "Unknown"),
                    short_name=item.get("shortName"),
                    country=(item.get("area") or {}).get("name"),
                    founded=item.get("founded"),
                    venue=item.get("venue"),
                    **self._provenance(str(item["id"]), item),
                )
            )
        return results

    def _matches(self, competition_id: str, season_id: str) -> list[dict[str, Any]]:
        payload = self._get(f"/competitions/{competition_id}/matches", params={"season": season_id})
        return payload.get("matches", [])

    def fixtures(self, competition_id: str, season_id: str) -> list[FixtureDTO]:
        results: list[FixtureDTO] = []
        for match in self._matches(competition_id, season_id):
            results.append(
                FixtureDTO(
                    fixture_id=str(match["id"]),
                    competition_id=str(competition_id),
                    season_id=str(season_id),
                    round=str(match.get("matchday")) if match.get("matchday") is not None else None,
                    kickoff_utc=_parse_datetime(match.get("utcDate")),
                    home_team_id=str(match["homeTeam"]["id"]),
                    away_team_id=str(match["awayTeam"]["id"]),
                    venue=None,
                    status=_STATUS_MAP.get(match.get("status", ""), "SCHEDULED"),
                    **self._provenance(str(match["id"]), match),
                )
            )
        return results

    def results(self, competition_id: str, season_id: str) -> list[ResultDTO]:
        results: list[ResultDTO] = []
        for match in self._matches(competition_id, season_id):
            if match.get("status") != "FINISHED":
                continue
            score = match.get("score", {})
            full_time = score.get("fullTime", {})
            half_time = score.get("halfTime", {})
            if full_time.get("home") is None or full_time.get("away") is None:
                continue
            results.append(
                ResultDTO(
                    fixture_id=str(match["id"]),
                    home_goals=full_time["home"],
                    away_goals=full_time["away"],
                    home_goals_first_half=half_time.get("home"),
                    away_goals_first_half=half_time.get("away"),
                    **self._provenance(str(match["id"]), match),
                )
            )
        return results

    def statistics(self, fixture_id: str) -> list[StatisticDTO]:
        logger.info("statistics_unavailable", provider=self.name, fixture_id=fixture_id)
        return []

    def xg(self, fixture_id: str) -> XGDTO | None:
        logger.info("xg_unavailable", provider=self.name, fixture_id=fixture_id)
        return None


def _parse_date(value: str | None) -> dt.date | None:
    return dt.date.fromisoformat(value) if value else None


def _parse_datetime(value: str | None) -> dt.datetime | None:
    if not value:
        return None
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _infer_season_status(start: str | None, end: str | None) -> str:
    if not start or not end:
        return "UNKNOWN"
    today = dt.date.today()
    start_date, end_date = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    if today < start_date:
        return "UPCOMING"
    if today > end_date:
        return "FINISHED"
    return "ACTIVE"
