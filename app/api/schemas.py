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


class SyncReportOut(BaseModel):
    provider: str
    started_at: dt.datetime
    finished_at: dt.datetime | None
    competitions_discovered: int
    new_competitions: list[str]
    updated_competitions: list[str]
    new_seasons: list[str]
    updated_seasons: list[str]
    errors: list[str]


class SystemHealthOut(BaseModel):
    status: str
    data_provider: str
    competitions_total: int
    active_competitions: int
    database_url_scheme: str
