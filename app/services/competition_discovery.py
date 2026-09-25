"""Automatic competition discovery — MASTER BUILD PROMPT section 3 (+ season
detection from section 4). Never assumes a competition still exists just
because it did last run: every run re-derives state from the provider.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.data.providers.base import FootballDataProvider, ProviderError
from app.data.providers.schemas import CompetitionDTO, SeasonDTO
from app.database.models.competitions import Competition, Season
from app.database.models.enums import (
    CompetitionFormat,
    CompetitionStatus,
    CompetitionType,
    DataQualityStatus,
    SeasonStatus,
)
from app.database.models.monitoring import SystemEvent
from app.logging_config import get_logger
from app.services.enum_utils import safe_enum
from app.services.identifiers import canonical_id
from app.services.season_detection import detect_season_window, infer_season_status

logger = get_logger(__name__)


@dataclass
class CompetitionDiscoveryReport:
    provider: str
    started_at: dt.datetime
    finished_at: dt.datetime | None = None
    competitions_discovered: int = 0
    new_competitions: list[str] = field(default_factory=list)
    updated_competitions: list[str] = field(default_factory=list)
    new_seasons: list[str] = field(default_factory=list)
    updated_seasons: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class CompetitionDiscoveryService:
    def __init__(self, db: Session, provider: FootballDataProvider) -> None:
        self.db = db
        self.provider = provider

    def run(self) -> CompetitionDiscoveryReport:
        report = CompetitionDiscoveryReport(provider=self.provider.name, started_at=dt.datetime.now(dt.timezone.utc))

        try:
            competition_dtos = self.provider.competitions()
        except ProviderError as exc:
            report.errors.append(f"competitions(): {exc}")
            logger.error("competition_discovery_failed", provider=self.provider.name, error=str(exc))
            self._record_event("COMPETITION_DISCOVERY_FAILED", "ERROR", str(exc))
            report.finished_at = dt.datetime.now(dt.timezone.utc)
            return report

        report.competitions_discovered = len(competition_dtos)

        for dto in competition_dtos:
            try:
                self._discover_one(dto, report)
            except ProviderError as exc:
                msg = f"{dto.competition_id}: {exc}"
                report.errors.append(msg)
                logger.error("competition_discovery_item_failed", competition_id=dto.competition_id, error=str(exc))

        self.db.commit()
        report.finished_at = dt.datetime.now(dt.timezone.utc)
        self._record_event(
            "COMPETITION_DISCOVERY_COMPLETED",
            "INFO",
            f"discovered={report.competitions_discovered} new={len(report.new_competitions)} "
            f"updated={len(report.updated_competitions)} errors={len(report.errors)}",
        )
        return report

    def _discover_one(self, dto: CompetitionDTO, report: CompetitionDiscoveryReport) -> None:
        canonical_competition_id = canonical_id(self.provider.name, dto.competition_id)
        competition = self.db.query(Competition).filter_by(canonical_competition_id=canonical_competition_id).first()
        is_new = competition is None

        if is_new:
            competition = Competition(canonical_competition_id=canonical_competition_id)
            self.db.add(competition)

        competition.name = dto.competition_name
        competition.country = dto.country
        competition.region = dto.region
        competition.competition_type = safe_enum(CompetitionType, dto.competition_type, CompetitionType.UNKNOWN)
        competition.division_level = dto.division_level
        competition.competition_format = safe_enum(
            CompetitionFormat, dto.competition_format, CompetitionFormat.UNKNOWN
        )
        competition.number_of_teams = dto.number_of_teams
        competition.source_provider = dto.source_provider
        competition.source_record_id = dto.source_record_id
        competition.retrieved_at = dto.retrieved_at
        competition.validation_status = "VALID"

        if is_new:
            competition.status = CompetitionStatus.DISCOVERED
            competition.data_quality_status = DataQualityStatus.INSUFFICIENT
            report.new_competitions.append(canonical_competition_id)
        elif competition.status == CompetitionStatus.ARCHIVED:
            # Reappeared after being archived — send it back through validation
            # rather than assuming it can resume production forecasting.
            competition.status = CompetitionStatus.VALIDATING
            report.updated_competitions.append(canonical_competition_id)
        else:
            report.updated_competitions.append(canonical_competition_id)

        self.db.flush()  # need competition.id for seasons

        seasons = self.provider.seasons(dto.competition_id)
        window = detect_season_window(seasons)
        for season_dto in seasons:
            self._upsert_season(competition, season_dto, window, report)

    def _upsert_season(
        self,
        competition: Competition,
        dto: SeasonDTO,
        window,
        report: CompetitionDiscoveryReport,
    ) -> None:
        season = (
            self.db.query(Season)
            .filter_by(competition_id=competition.id, canonical_season_id=dto.season_id)
            .first()
        )
        is_new = season is None
        if is_new:
            season = Season(competition_id=competition.id, canonical_season_id=dto.season_id)
            self.db.add(season)

        season.name = dto.name
        season.start_date = dto.start_date
        season.end_date = dto.end_date
        season.status = safe_enum(SeasonStatus, infer_season_status(window, dto), SeasonStatus.FINISHED)
        season.source_provider = dto.source_provider
        season.source_record_id = dto.source_record_id
        season.retrieved_at = dto.retrieved_at
        season.validation_status = "VALID"

        label = f"{competition.canonical_competition_id}:{dto.season_id}"
        (report.new_seasons if is_new else report.updated_seasons).append(label)

    def _record_event(self, event_type: str, severity: str, message: str) -> None:
        self.db.add(
            SystemEvent(event_type=event_type, severity=severity, message=message, context={"provider": self.provider.name})
        )
        self.db.commit()
