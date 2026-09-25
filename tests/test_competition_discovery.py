from app.data.providers.mock_provider import MockProvider
from app.database.models.competitions import Competition, Season
from app.database.models.enums import CompetitionStatus
from app.database.models.monitoring import SystemEvent
from app.services.competition_discovery import CompetitionDiscoveryService


def test_discovers_all_mock_competitions_and_seasons(db_session):
    service = CompetitionDiscoveryService(db_session, MockProvider())
    report = service.run()

    assert report.competitions_discovered == 2
    assert len(report.new_competitions) == 2
    assert not report.errors

    competitions = db_session.query(Competition).all()
    assert {c.canonical_competition_id for c in competitions} == {"mock:MOCK-D1", "mock:MOCK-D2"}
    for c in competitions:
        assert c.status == CompetitionStatus.DISCOVERED
        assert c.name

    seasons = db_session.query(Season).all()
    # MOCK-D1 has 2 seasons, MOCK-D2 has 1
    assert len(seasons) == 3


def test_second_run_updates_rather_than_duplicates(db_session):
    provider = MockProvider()
    first_report = CompetitionDiscoveryService(db_session, provider).run()
    second_report = CompetitionDiscoveryService(db_session, provider).run()

    assert len(first_report.new_competitions) == 2
    assert len(second_report.new_competitions) == 0
    assert len(second_report.updated_competitions) == 2

    competitions = db_session.query(Competition).all()
    assert len(competitions) == 2  # no duplicates

    seasons = db_session.query(Season).all()
    assert len(seasons) == 3  # no duplicates


def test_discovery_emits_system_event(db_session):
    CompetitionDiscoveryService(db_session, MockProvider()).run()
    events = db_session.query(SystemEvent).filter_by(event_type="COMPETITION_DISCOVERY_COMPLETED").all()
    assert len(events) == 1


def test_season_status_reflects_active_window(db_session):
    CompetitionDiscoveryService(db_session, MockProvider()).run()
    competition = db_session.query(Competition).filter_by(canonical_competition_id="mock:MOCK-D1").one()
    seasons = {s.canonical_season_id: s for s in competition.seasons}
    assert seasons["2026"].status.value == "ACTIVE"
    assert seasons["2024"].status.value == "FINISHED"
