"""Provider-agnostic data-transfer objects.

Every concrete provider adapter (football-data.org, a future secondary
provider, the offline mock) must translate its native payloads into these
shapes. The forecasting engine and services only ever see these DTOs —
never a provider's raw JSON — which is what keeps everything upstream of
here provider-agnostic (MASTER BUILD PROMPT section 8).
"""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict


class ProvenanceFields(BaseModel):
    model_config = ConfigDict(frozen=True)

    source_provider: str
    source_record_id: str
    retrieved_at: dt.datetime
    raw_payload: dict


class CompetitionDTO(ProvenanceFields):
    competition_id: str
    competition_name: str
    country: str | None = None
    region: str | None = None
    competition_type: str | None = None
    division_level: int | None = None
    season_id: str | None = None
    season_name: str | None = None
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    status: str | None = None
    number_of_teams: int | None = None
    competition_format: str | None = None


class SeasonDTO(ProvenanceFields):
    competition_id: str
    season_id: str
    name: str
    start_date: dt.date | None = None
    end_date: dt.date | None = None
    status: str | None = None
    current_matchday: int | None = None


class TeamDTO(ProvenanceFields):
    team_id: str
    name: str
    short_name: str | None = None
    country: str | None = None
    founded: int | None = None
    venue: str | None = None


class FixtureDTO(ProvenanceFields):
    fixture_id: str
    competition_id: str
    season_id: str
    round: str | None = None
    kickoff_utc: dt.datetime | None = None
    home_team_id: str
    away_team_id: str
    venue: str | None = None
    status: str


class ResultDTO(ProvenanceFields):
    fixture_id: str
    home_goals: int
    away_goals: int
    home_goals_first_half: int | None = None
    away_goals_first_half: int | None = None


class StatisticDTO(ProvenanceFields):
    fixture_id: str
    team_id: str
    stat_name: str
    stat_value: float


class XGDTO(ProvenanceFields):
    fixture_id: str
    home_xg: float | None = None
    away_xg: float | None = None
    home_xg_first_half: float | None = None
    away_xg_first_half: float | None = None
