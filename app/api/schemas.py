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


class ScorelineOut(BaseModel):
    home_goals: int
    away_goals: int
    probability: float


class ExpectedGoalsOut(BaseModel):
    home: float | None
    away: float | None
    total: float | None


class OutcomeDistributionOut(BaseModel):
    home_win: float
    draw: float
    away_win: float


class GoalDistributionOut(BaseModel):
    buckets: dict[str, float]
    expected_total_goals: float
    median_total_goals: int
    mode_total_goals: int
    variance_total_goals: float
    over_under: dict[str, float]
    btts_probability: float
    home_clean_sheet_probability: float
    away_clean_sheet_probability: float
    no_goals_probability: float


class ModelDiagnosticsOut(BaseModel):
    model_disagreement: str | None
    aleatoric_uncertainty: float | None
    epistemic_uncertainty: float | None
    data_quality_score: float | None
    ood_status: bool


class ModelInformationOut(BaseModel):
    champion_model: str | None
    supporting_models: list[str]
    model_version: str | None
    dataset_version: str | None
    feature_version: str
    software_version: str
    predicted_at: dt.datetime


class AdministratorNotesOut(BaseModel):
    warnings: list[str]
    errors: list[str]


class MatchForecastOut(BaseModel):
    """MASTER BUILD PROMPT section 62 output format. `most_probable_scorelines`
    are exactly that — a summary of the score matrix, never a guarantee."""

    prediction_id: str
    competition_canonical_id: str
    season_canonical_id: str
    fixture_canonical_id: str
    kickoff_utc: dt.datetime | None
    home_team: str
    away_team: str
    forecast_status: str
    expected_goals: ExpectedGoalsOut
    most_probable_scorelines: list[ScorelineOut]
    outcome_distribution: OutcomeDistributionOut | None
    goal_distribution: GoalDistributionOut | None
    model_diagnostics: ModelDiagnosticsOut
    model_information: ModelInformationOut
    administrator_notes: AdministratorNotesOut
