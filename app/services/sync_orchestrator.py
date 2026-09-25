"""Full synchronization pipeline — MASTER BUILD PROMPT section 51 (steps
1-7 of that list; steps 8+ are model training/calibration, added in later
phases). Wires together: discover competitions/seasons -> map teams ->
sync fixtures/results/statistics/xG -> detect promotion/relegation ->
score data quality -> move competitions through their lifecycle.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.data.providers.base import FootballDataProvider
from app.database.models.competitions import Competition, Season
from app.database.models.enums import DataQualityStatus, SeasonStatus
from app.database.models.monitoring import SystemEvent
from app.logging_config import get_logger
from app.services.competition_discovery import CompetitionDiscoveryReport, CompetitionDiscoveryService
from app.services.data_quality import DataQualityService
from app.services.fixture_sync import FixtureSyncService
from app.services.movement_detection import MovementDetectionService, MovementReport
from app.services.team_mapping import TeamMappingService

logger = get_logger(__name__)


@dataclass
class FullSyncReport:
    provider: str
    started_at: dt.datetime
    finished_at: dt.datetime | None = None
    discovery: CompetitionDiscoveryReport | None = None
    new_teams: int = 0
    renamed_teams: int = 0
    new_fixtures: int = 0
    updated_fixtures: int = 0
    new_results: int = 0
    data_quality_summary: dict[str, str] = field(default_factory=dict)
    movements: MovementReport | None = None
    errors: list[str] = field(default_factory=list)


class FullSyncService:
    """Sync depth is deliberately bounded to the current season plus the
    single most recent finished one — enough for team mapping, promotion/
    relegation detection and a baseline of historical results, without
    hammering a rate-limited provider on every run. A deeper backfill is a
    separate, explicit operation rather than something `/sync` does by default.
    """

    def __init__(self, db: Session, provider: FootballDataProvider) -> None:
        self.db = db
        self.provider = provider

    def run(self) -> FullSyncReport:
        report = FullSyncReport(provider=self.provider.name, started_at=dt.datetime.now(dt.timezone.utc))

        report.discovery = CompetitionDiscoveryService(self.db, self.provider).run()
        report.errors.extend(report.discovery.errors)

        competitions = self.db.query(Competition).all()

        for competition in competitions:
            try:
                self._sync_competition(competition, report)
            except Exception as exc:  # keep one competition's failure from aborting the whole run
                msg = f"{competition.canonical_competition_id}: {exc}"
                report.errors.append(msg)
                logger.error("full_sync_competition_failed", competition=competition.canonical_competition_id, error=str(exc))

        report.movements = MovementDetectionService(self.db).detect(competitions)

        report.finished_at = dt.datetime.now(dt.timezone.utc)
        self.db.add(
            SystemEvent(
                event_type="FULL_SYNC_COMPLETED",
                severity="INFO",
                message=(
                    f"competitions={len(competitions)} new_fixtures={report.new_fixtures} "
                    f"new_results={report.new_results} errors={len(report.errors)}"
                ),
                context={"provider": self.provider.name},
            )
        )
        self.db.commit()
        return report

    def _relevant_seasons(self, competition: Competition) -> list[Season]:
        seasons = (
            self.db.query(Season)
            .filter(Season.competition_id == competition.id, Season.status.in_([SeasonStatus.ACTIVE, SeasonStatus.FINISHED]))
            .order_by(Season.end_date.desc().nullslast())
            .all()
        )
        active = [s for s in seasons if s.status == SeasonStatus.ACTIVE]
        finished = [s for s in seasons if s.status == SeasonStatus.FINISHED]
        return active[:1] + finished[:1]

    def _sync_competition(self, competition: Competition, report: FullSyncReport) -> None:
        for season in self._relevant_seasons(competition):
            team_report = TeamMappingService(self.db, self.provider).sync_teams(
                competition.source_record_id, season.canonical_season_id
            )
            report.new_teams += len(team_report.new_teams)
            report.renamed_teams += len(team_report.renamed_teams)
            report.errors.extend(team_report.errors)

            fixture_report = FixtureSyncService(self.db, self.provider).sync(competition, season)
            report.new_fixtures += len(fixture_report.new_fixtures)
            report.updated_fixtures += len(fixture_report.updated_fixtures)
            report.new_results += len(fixture_report.new_results)
            report.errors.extend(fixture_report.errors)

            quality = DataQualityService(self.db).evaluate(competition, season, extra_issues=fixture_report.rejected)
            report.data_quality_summary[f"{competition.canonical_competition_id}:{season.canonical_season_id}"] = (
                quality.status.value if isinstance(quality.status, DataQualityStatus) else str(quality.status)
            )
