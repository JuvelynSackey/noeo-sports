"""Pydantic response models for the API. Deliberately thin for Phase 1 —
forecast/model/calibration schemas land in later phases alongside the
models that produce them."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel, ConfigDict


class SeasonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    canonical_season_id: str
    name: str
    start_date: dt.date | None
    end_date: dt.date | None
    status: str


class CompetitionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    canonical_competition_id: str
    name: str
    country: str | None
    competition_type: str
    division_level: int | None
    competition_format: str
    status: str
    data_quality_status: str
    number_of_teams: int | None


class CompetitionDetailOut(CompetitionOut):
    seasons: list[SeasonOut]


class DiscoveryReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    competitions_discovered: int
    new_competitions: list[str]
    updated_competitions: list[str]
    new_seasons: list[str]
    updated_seasons: list[str]
    errors: list[str]


class MovementReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    promoted: list[tuple[str, str, str]]
    relegated: list[tuple[str, str, str]]
    new_teams: list[tuple[str, str]]
    departed_teams: list[tuple[str, str]]


class SyncReportOut(BaseModel):
    provider: str
    started_at: dt.datetime
    finished_at: dt.datetime | None
    discovery: DiscoveryReportOut | None
    new_teams: int
    renamed_teams: int
    new_fixtures: int
    updated_fixtures: int
    new_results: int
    data_quality_summary: dict[str, str]
    movements: MovementReportOut | None
    errors: list[str]


class SystemHealthOut(BaseModel):
    status: str
    data_provider: str
    competitions_total: int
    active_competitions: int
    database_url_scheme: str


class TeamOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    canonical_team_id: str
    current_name: str
    country: str | None
    is_reserve_team: bool
    is_dissolved: bool


class ResultOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    home_goals: int
    away_goals: int
    home_goals_first_half: int | None
    away_goals_first_half: int | None


class FixtureOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    canonical_fixture_id: str
    round: str | None
    kickoff_utc: dt.datetime | None
    status: str
    home_team: TeamOut
    away_team: TeamOut
    result: ResultOut | None


class DataQualityOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    competition_canonical_id: str
    season_canonical_id: str
    overall_score: float
    status: str
    completeness: float | None
    freshness: float | None
    source_reliability: float | None
    team_mapping_quality: float | None
    fixture_completeness: float | None
    issues: list[str]
    evaluated_at: dt.datetime


class LeagueParameterOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    competition_canonical_id: str
    season_canonical_id: str
    avg_home_goals: float | None
    avg_away_goals: float | None
    avg_total_goals: float | None
    home_advantage: float | None
    draw_frequency: float | None
    scoring_variance: float | None
    sample_size: int
    shrinkage_applied: bool
    computed_at: dt.datetime


class TeamStrengthOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    team_canonical_id: str
    competition_canonical_id: str
    as_of: dt.datetime
    attack_strength: float | None
    defence_strength: float | None
    home_strength: float | None
    away_strength: float | None
    opponent_adjusted_strength: float | None
    recent_strength: float | None
    uncertainty: float | None
    method: str | None


class ModelVersionSummaryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    model_name: str
    version: str
    status: str
    disabled_reason: str | None
    competition_canonical_id: str | None
    trained_at: dt.datetime | None
    training_window_start: dt.datetime | None
    training_window_end: dt.datetime | None
    evaluation_metrics: dict | None
    is_reproducible: bool


class ModelVersionDetailOut(ModelVersionSummaryOut):
    # NOTE: raw model parameters (section 54: administrator-only diagnostics).
    # Exposed here because auth/RBAC isn't wired up yet (Phase 10) — restrict
    # this endpoint's audience accordingly until it is.
    hyperparameters: dict | None
    parameters: dict | None
