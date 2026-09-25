import datetime as dt

from app.database.models.competitions import Competition, Season
from app.database.models.enums import CompetitionFormat, CompetitionStatus, DataQualityStatus, FixtureStatus
from app.database.models.fixtures import Fixture, Result
from app.database.models.quality import DataQuality
from app.database.models.teams import Team
from app.services.data_quality import DataQualityService


def _competition(**overrides) -> Competition:
    defaults = dict(
        canonical_competition_id="prov:C1",
        name="Test League",
        source_provider="prov",
        source_record_id="C1",
        retrieved_at=dt.datetime.now(dt.timezone.utc),
        number_of_teams=4,
        competition_format=CompetitionFormat.SINGLE_ROUND_ROBIN,
        status=CompetitionStatus.DISCOVERED,
    )
    defaults.update(overrides)
    return Competition(**defaults)


def _team(db_session, tid: str) -> Team:
    team = Team(
        canonical_team_id=tid,
        current_name=tid,
        source_provider="prov",
        source_record_id=tid,
        retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    db_session.add(team)
    db_session.commit()
    return team


def _season(competition: Competition) -> Season:
    return Season(
        competition_id=competition.id,
        canonical_season_id="2025",
        name="2025",
        source_provider="prov",
        source_record_id="s1",
        retrieved_at=dt.datetime.now(dt.timezone.utc),
    )


def _fixture(competition, season, home, away, status, retrieved_at=None) -> Fixture:
    return Fixture(
        canonical_fixture_id=f"prov:F-{home.id}-{away.id}-{status}",
        competition_id=competition.id,
        season_id=season.id,
        home_team_id=home.id,
        away_team_id=away.id,
        status=status,
        source_provider="prov",
        source_record_id=f"F-{home.id}-{away.id}",
        retrieved_at=retrieved_at or dt.datetime.now(dt.timezone.utc),
        validation_status="VALID",
    )


def test_full_data_promotes_competition_to_active(db_session):
    competition = _competition(number_of_teams=4)  # single round robin, 4 teams -> 6 fixtures expected
    db_session.add(competition)
    db_session.commit()
    season = _season(competition)
    db_session.add(season)
    db_session.commit()

    teams = [_team(db_session, f"prov:T{i}") for i in range(4)]
    pairs = [(0, 1), (2, 3), (0, 2), (1, 3), (0, 3), (1, 2)]
    for h, a in pairs:
        fixture = _fixture(competition, season, teams[h], teams[a], FixtureStatus.COMPLETED)
        db_session.add(fixture)
        db_session.flush()
        db_session.add(Result(fixture_id=fixture.id, home_goals=1, away_goals=0, source_provider="prov",
                               source_record_id=fixture.canonical_fixture_id, retrieved_at=dt.datetime.now(dt.timezone.utc),
                               validation_status="VALID"))
    db_session.commit()

    report = DataQualityService(db_session).evaluate(competition, season)

    assert report.overall_score == 1.0
    assert report.status == DataQualityStatus.EXCELLENT
    assert competition.status == CompetitionStatus.ACTIVE
    assert competition.data_quality_status == DataQualityStatus.EXCELLENT

    stored = db_session.query(DataQuality).filter_by(competition_id=competition.id, season_id=season.id).one()
    assert stored.overall_score == 1.0


def test_missing_results_and_teams_reduce_score_and_flag_limited_data(db_session):
    competition = _competition(number_of_teams=4)
    db_session.add(competition)
    db_session.commit()
    season = _season(competition)
    db_session.add(season)
    db_session.commit()

    # Only 2 of 4 expected teams show up, only 1 of 6 expected fixtures exists, and it has no result.
    teams = [_team(db_session, f"prov:T{i}") for i in range(2)]
    fixture = _fixture(competition, season, teams[0], teams[1], FixtureStatus.COMPLETED)
    db_session.add(fixture)
    db_session.commit()

    report = DataQualityService(db_session).evaluate(competition, season)

    assert report.overall_score < 0.75  # good data quality is out of reach with this much missing
    assert report.status in (DataQualityStatus.LIMITED, DataQualityStatus.INSUFFICIENT)
    assert report.issues  # human-readable reasons must be recorded
    assert competition.status in (CompetitionStatus.LIMITED_DATA, CompetitionStatus.VALIDATING)


def test_stale_data_reduces_freshness_score(db_session):
    competition = _competition(number_of_teams=2, competition_format=CompetitionFormat.UNKNOWN)
    db_session.add(competition)
    db_session.commit()
    season = _season(competition)
    db_session.add(season)
    db_session.commit()

    teams = [_team(db_session, f"prov:T{i}") for i in range(2)]
    old = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=60)
    fixture = _fixture(competition, season, teams[0], teams[1], FixtureStatus.COMPLETED, retrieved_at=old)
    db_session.add(fixture)
    db_session.flush()
    db_session.add(Result(fixture_id=fixture.id, home_goals=1, away_goals=1, source_provider="prov",
                           source_record_id="r1", retrieved_at=old, validation_status="VALID"))
    db_session.commit()

    report = DataQualityService(db_session).evaluate(competition, season)

    assert report.freshness == 0.0
    assert any("not refreshed" in issue for issue in report.issues)


def test_no_fixtures_yields_zero_score_and_insufficient_status(db_session):
    competition = _competition()
    db_session.add(competition)
    db_session.commit()
    season = _season(competition)
    db_session.add(season)
    db_session.commit()

    report = DataQualityService(db_session).evaluate(competition, season)

    assert report.overall_score == 0.0
    assert report.status == DataQualityStatus.INSUFFICIENT
