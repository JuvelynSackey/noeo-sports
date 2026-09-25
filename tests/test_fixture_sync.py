import datetime as dt

from app.data.providers.mock_provider import MockProvider
from app.data.providers.schemas import ResultDTO
from app.database.models.competitions import Competition, Season
from app.database.models.enums import FixtureStatus
from app.database.models.fixtures import Fixture, Result, XGData
from app.services.fixture_sync import FixtureSyncService
from app.services.team_mapping import TeamMappingService


def _setup_competition_and_season(db_session, competition_id="MOCK-D1", season_id="2024"):
    competition = Competition(
        canonical_competition_id=f"mock:{competition_id}",
        name="Noeo Mock Division One",
        source_provider="mock",
        source_record_id=competition_id,
        retrieved_at=dt.datetime.now(dt.timezone.utc),
        number_of_teams=6,
    )
    db_session.add(competition)
    db_session.commit()
    season = Season(
        competition_id=competition.id,
        canonical_season_id=season_id,
        name=season_id,
        source_provider="mock",
        source_record_id=season_id,
        retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    db_session.add(season)
    db_session.commit()
    return competition, season


def test_fixtures_and_results_ingested_after_teams_are_mapped(db_session):
    provider = MockProvider()
    competition, season = _setup_competition_and_season(db_session)
    TeamMappingService(db_session, provider).sync_teams("MOCK-D1", "2024")

    report = FixtureSyncService(db_session, provider).sync(competition, season)

    assert len(report.new_fixtures) == 15  # single round robin, 6 teams
    assert report.new_results  # 2024 season is fully finished in the mock world
    assert not report.errors
    assert not report.skipped_missing_team

    fixtures = db_session.query(Fixture).filter_by(competition_id=competition.id, season_id=season.id).all()
    assert len(fixtures) == 15
    completed = [f for f in fixtures if f.status == FixtureStatus.COMPLETED]
    assert len(completed) == len(fixtures)  # 2024 season fully in the past
    assert db_session.query(Result).count() == len(completed)


def test_fixtures_skipped_when_team_not_mapped(db_session):
    provider = MockProvider()
    competition, season = _setup_competition_and_season(db_session)
    # Deliberately skip TeamMappingService — no teams exist yet.

    report = FixtureSyncService(db_session, provider).sync(competition, season)

    assert not report.new_fixtures
    assert len(report.skipped_missing_team) == 15
    assert db_session.query(Fixture).count() == 0


def test_rerun_is_idempotent(db_session):
    provider = MockProvider()
    competition, season = _setup_competition_and_season(db_session)
    TeamMappingService(db_session, provider).sync_teams("MOCK-D1", "2024")
    service = FixtureSyncService(db_session, provider)

    service.sync(competition, season)
    second_report = service.sync(competition, season)

    assert not second_report.new_fixtures
    assert len(second_report.updated_fixtures) == 15
    assert db_session.query(Fixture).count() == 15
    assert db_session.query(Result).count() == 15


def test_statistics_and_xg_ingested_for_completed_fixtures(db_session):
    provider = MockProvider()
    competition, season = _setup_competition_and_season(db_session)
    TeamMappingService(db_session, provider).sync_teams("MOCK-D1", "2024")

    FixtureSyncService(db_session, provider).sync(competition, season)

    from app.database.models.fixtures import MatchStatistic

    assert db_session.query(MatchStatistic).count() > 0
    # The mock provider never reports xG — it must not be fabricated.
    assert db_session.query(XGData).count() == 0


def test_negative_score_rejected(db_session, monkeypatch):
    provider = MockProvider()
    competition, season = _setup_competition_and_season(db_session)
    TeamMappingService(db_session, provider).sync_teams("MOCK-D1", "2024")

    bad_result = ResultDTO(
        fixture_id="MOCK-D1:2024:000",
        home_goals=-1,
        away_goals=2,
        source_provider="mock",
        source_record_id="MOCK-D1:2024:000",
        retrieved_at=dt.datetime.now(dt.timezone.utc),
        raw_payload={},
    )
    monkeypatch.setattr(provider, "results", lambda *a, **k: [bad_result])

    service = FixtureSyncService(db_session, provider)
    report = service.sync(competition, season)

    assert any("implausible score" in r for r in report.rejected)
    assert db_session.query(Result).count() == 0
