import datetime as dt

import pytest
from sqlalchemy.exc import IntegrityError

from app.database.models.competitions import Competition, Season
from app.database.models.enums import CompetitionStatus
from app.database.models.fixtures import Fixture, Result
from app.database.models.teams import Team


def _make_competition(**overrides) -> Competition:
    defaults = dict(
        canonical_competition_id="prov:C1",
        name="Test League",
        source_provider="prov",
        source_record_id="C1",
        retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    defaults.update(overrides)
    return Competition(**defaults)


def test_duplicate_canonical_competition_id_rejected(db_session):
    db_session.add(_make_competition())
    db_session.commit()

    db_session.add(_make_competition(source_record_id="C1-dup"))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_competition_defaults_to_discovered_status(db_session):
    competition = _make_competition()
    db_session.add(competition)
    db_session.commit()
    assert competition.status == CompetitionStatus.DISCOVERED


def test_season_unique_per_competition(db_session):
    competition = _make_competition()
    db_session.add(competition)
    db_session.commit()

    season_kwargs = dict(
        competition_id=competition.id,
        canonical_season_id="2025",
        name="2025",
        source_provider="prov",
        source_record_id="s1",
        retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    db_session.add(Season(**season_kwargs))
    db_session.commit()

    db_session.add(Season(**{**season_kwargs, "source_record_id": "s1-dup"}))
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()


def test_fixture_requires_valid_team_and_result_is_one_to_one(db_session):
    competition = _make_competition()
    db_session.add(competition)
    db_session.commit()

    season = Season(
        competition_id=competition.id,
        canonical_season_id="2025",
        name="2025",
        source_provider="prov",
        source_record_id="s1",
        retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    home = Team(
        canonical_team_id="prov:T1",
        current_name="Home FC",
        source_provider="prov",
        source_record_id="T1",
        retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    away = Team(
        canonical_team_id="prov:T2",
        current_name="Away FC",
        source_provider="prov",
        source_record_id="T2",
        retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    db_session.add_all([season, home, away])
    db_session.commit()

    fixture = Fixture(
        canonical_fixture_id="prov:F1",
        competition_id=competition.id,
        season_id=season.id,
        home_team_id=home.id,
        away_team_id=away.id,
        source_provider="prov",
        source_record_id="F1",
        retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    db_session.add(fixture)
    db_session.commit()

    result = Result(
        fixture_id=fixture.id,
        home_goals=2,
        away_goals=1,
        source_provider="prov",
        source_record_id="F1",
        retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    db_session.add(result)
    db_session.commit()

    assert fixture.result.home_goals == 2

    duplicate_result = Result(
        fixture_id=fixture.id,
        home_goals=0,
        away_goals=0,
        source_provider="prov",
        source_record_id="F1-2",
        retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    db_session.add(duplicate_result)
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()
