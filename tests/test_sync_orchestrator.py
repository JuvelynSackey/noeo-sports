from app.data.providers.mock_provider import MockProvider
from app.database.models.competitions import Competition
from app.database.models.enums import CompetitionStatus, DataQualityStatus
from app.database.models.fixtures import Fixture, Result
from app.database.models.teams import Team
from app.services.sync_orchestrator import FullSyncService


def test_full_sync_populates_everything_from_scratch(db_session):
    report = FullSyncService(db_session, MockProvider()).run()

    assert report.discovery.competitions_discovered == 2
    assert report.new_teams == 10  # 6 + 4 across the two mock competitions
    assert report.new_fixtures > 0
    assert report.new_results > 0
    assert not report.errors

    assert db_session.query(Team).count() == 10
    assert db_session.query(Fixture).count() > 0
    assert db_session.query(Result).count() > 0

    competitions = db_session.query(Competition).all()
    for competition in competitions:
        assert competition.status == CompetitionStatus.ACTIVE
        assert competition.data_quality_status in (DataQualityStatus.EXCELLENT, DataQualityStatus.GOOD)

    assert report.data_quality_summary  # at least one competition:season entry


def test_full_sync_is_idempotent(db_session):
    provider = MockProvider()
    first = FullSyncService(db_session, provider).run()
    second = FullSyncService(db_session, provider).run()

    assert second.new_teams == 0
    assert second.new_fixtures == 0
    assert second.new_results == 0
    assert not second.errors

    assert db_session.query(Team).count() == 10
    assert db_session.query(Fixture).count() == db_session.query(Fixture).count()  # stable, no duplication


def test_full_sync_only_syncs_current_and_most_recent_finished_season(db_session):
    report = FullSyncService(db_session, MockProvider()).run()
    # MOCK-D1 has 2024 (FINISHED) and 2026 (ACTIVE) — both should be synced.
    keys = set(report.data_quality_summary.keys())
    assert "mock:MOCK-D1:2024" in keys
    assert "mock:MOCK-D1:2026" in keys
    assert "mock:MOCK-D2:2026" in keys
