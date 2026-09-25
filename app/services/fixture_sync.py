"""Fixture/result/statistics/xG synchronization — MASTER BUILD PROMPT
section 11 (fixtures), plus the historical-ingestion half of Phase 2.

Canonical fixture ids prevent duplicates; results/statistics/xG are upserted
against the fixture rather than blindly appended. Implausible values (a
negative score, a statistic outside any realistic range) are rejected
rather than stored, and never fabricated when a provider simply doesn't
have them (section 20) — that's why `xg()` returning None just skips the
XGData row instead of writing zeros.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy.orm import Session

from app.data.providers.base import FootballDataProvider
from app.database.models.competitions import Competition, Season
from app.database.models.enums import FixtureStatus
from app.database.models.fixtures import Fixture, MatchStatistic, Result, XGData
from app.database.models.teams import Team
from app.logging_config import get_logger
from app.services.enum_utils import safe_enum
from app.services.identifiers import canonical_id

logger = get_logger(__name__)

MAX_PLAUSIBLE_GOALS = 15
STAT_BOUNDS: dict[str, tuple[float, float]] = {
    "corners": (0, 30),
    "yellow_cards": (0, 15),
    "red_cards": (0, 5),
}


@dataclass
class FixtureSyncReport:
    new_fixtures: list[str] = field(default_factory=list)
    updated_fixtures: list[str] = field(default_factory=list)
    new_results: list[str] = field(default_factory=list)
    updated_results: list[str] = field(default_factory=list)
    new_statistics: int = 0
    new_xg: int = 0
    rejected: list[str] = field(default_factory=list)
    skipped_missing_team: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class FixtureSyncService:
    def __init__(self, db: Session, provider: FootballDataProvider) -> None:
        self.db = db
        self.provider = provider

    def sync(self, competition: Competition, season: Season) -> FixtureSyncReport:
        report = FixtureSyncReport()
        native_competition_id = competition.source_record_id
        native_season_id = season.canonical_season_id

        try:
            fixture_dtos = self.provider.fixtures(native_competition_id, native_season_id)
        except Exception as exc:
            report.errors.append(f"fixtures(): {exc}")
            logger.error("fixture_sync_failed", competition=competition.canonical_competition_id, error=str(exc))
            return report

        fixtures_by_canonical_id: dict[str, Fixture] = {}
        for dto in fixture_dtos:
            fixture = self._upsert_fixture(dto, competition, season, report)
            if fixture is not None:
                fixtures_by_canonical_id[dto.fixture_id] = fixture
        self.db.flush()

        try:
            result_dtos = self.provider.results(native_competition_id, native_season_id)
        except Exception as exc:
            report.errors.append(f"results(): {exc}")
            logger.error("result_sync_failed", competition=competition.canonical_competition_id, error=str(exc))
            result_dtos = []

        for dto in result_dtos:
            fixture = fixtures_by_canonical_id.get(dto.fixture_id)
            if fixture is None:
                report.errors.append(f"result for unknown fixture {dto.fixture_id}")
                continue
            self._upsert_result(dto, fixture, report)

        for dto in fixture_dtos:
            fixture = fixtures_by_canonical_id.get(dto.fixture_id)
            if fixture is None or fixture.status != FixtureStatus.COMPLETED:
                continue
            self._sync_statistics(fixture, dto.fixture_id, report)
            self._sync_xg(fixture, dto.fixture_id, report)

        self.db.commit()
        return report

    def _resolve_team(self, native_team_id: str) -> Team | None:
        return self.db.query(Team).filter_by(canonical_team_id=canonical_id(self.provider.name, native_team_id)).first()

    def _upsert_fixture(self, dto, competition: Competition, season: Season, report: FixtureSyncReport) -> Fixture | None:
        home = self._resolve_team(dto.home_team_id)
        away = self._resolve_team(dto.away_team_id)
        if home is None or away is None:
            report.skipped_missing_team.append(dto.fixture_id)
            logger.warning("fixture_skipped_missing_team", fixture_id=dto.fixture_id)
            return None

        canonical_fixture_id = canonical_id(self.provider.name, dto.fixture_id)
        fixture = self.db.query(Fixture).filter_by(canonical_fixture_id=canonical_fixture_id).first()
        is_new = fixture is None
        if is_new:
            fixture = Fixture(canonical_fixture_id=canonical_fixture_id, competition_id=competition.id, season_id=season.id)
            self.db.add(fixture)

        fixture.round = dto.round
        fixture.kickoff_utc = dto.kickoff_utc
        fixture.home_team_id = home.id
        fixture.away_team_id = away.id
        fixture.venue = dto.venue
        fixture.status = safe_enum(FixtureStatus, dto.status, FixtureStatus.SCHEDULED)
        fixture.source_provider = dto.source_provider
        fixture.source_record_id = dto.source_record_id
        fixture.retrieved_at = dto.retrieved_at
        fixture.validation_status = "VALID"

        (report.new_fixtures if is_new else report.updated_fixtures).append(canonical_fixture_id)
        return fixture

    def _upsert_result(self, dto, fixture: Fixture, report: FixtureSyncReport) -> None:
        if not (0 <= dto.home_goals <= MAX_PLAUSIBLE_GOALS) or not (0 <= dto.away_goals <= MAX_PLAUSIBLE_GOALS):
            report.rejected.append(f"result {dto.fixture_id}: implausible score {dto.home_goals}-{dto.away_goals}")
            logger.warning("result_rejected", fixture_id=dto.fixture_id, home=dto.home_goals, away=dto.away_goals)
            return
        if dto.home_goals_first_half is not None and dto.home_goals_first_half > dto.home_goals:
            report.rejected.append(f"result {dto.fixture_id}: first-half home goals exceed full-time")
            return
        if dto.away_goals_first_half is not None and dto.away_goals_first_half > dto.away_goals:
            report.rejected.append(f"result {dto.fixture_id}: first-half away goals exceed full-time")
            return

        result = self.db.query(Result).filter_by(fixture_id=fixture.id).first()
        is_new = result is None
        if is_new:
            result = Result(fixture_id=fixture.id)
            self.db.add(result)

        result.home_goals = dto.home_goals
        result.away_goals = dto.away_goals
        result.home_goals_first_half = dto.home_goals_first_half
        result.away_goals_first_half = dto.away_goals_first_half
        result.source_provider = dto.source_provider
        result.source_record_id = dto.source_record_id
        result.retrieved_at = dto.retrieved_at
        result.validation_status = "VALID"

        (report.new_results if is_new else report.updated_results).append(dto.fixture_id)

    def _sync_statistics(self, fixture: Fixture, native_fixture_id: str, report: FixtureSyncReport) -> None:
        try:
            stat_dtos = self.provider.statistics(native_fixture_id)
        except Exception as exc:
            report.errors.append(f"statistics({native_fixture_id}): {exc}")
            return

        for dto in stat_dtos:
            bounds = STAT_BOUNDS.get(dto.stat_name)
            if bounds and not (bounds[0] <= dto.stat_value <= bounds[1]):
                report.rejected.append(f"statistic {dto.stat_name}={dto.stat_value} out of range for {native_fixture_id}")
                continue
            team = self._resolve_team(dto.team_id)
            if team is None:
                continue
            stat = (
                self.db.query(MatchStatistic)
                .filter_by(fixture_id=fixture.id, team_id=team.id, stat_name=dto.stat_name)
                .first()
            )
            if stat is None:
                stat = MatchStatistic(fixture_id=fixture.id, team_id=team.id, stat_name=dto.stat_name)
                self.db.add(stat)
                report.new_statistics += 1
            stat.stat_value = dto.stat_value
            stat.source_provider = dto.source_provider
            stat.source_record_id = dto.source_record_id
            stat.retrieved_at = dto.retrieved_at
            stat.validation_status = "VALID"

    def _sync_xg(self, fixture: Fixture, native_fixture_id: str, report: FixtureSyncReport) -> None:
        try:
            dto = self.provider.xg(native_fixture_id)
        except Exception as exc:
            report.errors.append(f"xg({native_fixture_id}): {exc}")
            return
        if dto is None:
            return  # provider genuinely has no xG for this fixture — never fabricate one

        xg = self.db.query(XGData).filter_by(fixture_id=fixture.id).first()
        is_new = xg is None
        if is_new:
            xg = XGData(fixture_id=fixture.id)
            self.db.add(xg)
            report.new_xg += 1

        xg.home_xg = dto.home_xg
        xg.away_xg = dto.away_xg
        xg.home_xg_first_half = dto.home_xg_first_half
        xg.away_xg_first_half = dto.away_xg_first_half
        xg.source_provider = dto.source_provider
        xg.source_record_id = dto.source_record_id
        xg.retrieved_at = dto.retrieved_at
        xg.validation_status = "VALID"
