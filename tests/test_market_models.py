import datetime as dt

from app.config import Settings
from app.database.models.competitions import Competition, Season
from app.database.models.enums import FixtureStatus, ModelStatus
from app.database.models.fixtures import Fixture, MatchStatistic, Result
from app.database.models.modeling import ModelVersion
from app.database.models.teams import Team
from app.services.market_models import CARDS_MODEL, CORNERS_MODEL, FIRST_HALF_MODEL, MarketModelTrainingService


def _competition(cid: str) -> Competition:
    return Competition(canonical_competition_id=cid, name=cid, source_provider="prov", source_record_id=cid,
                        retrieved_at=dt.datetime.now(dt.timezone.utc))


def _season(competition: Competition, sid: str) -> Season:
    return Season(competition_id=competition.id, canonical_season_id=sid, name=sid, source_provider="prov",
                  source_record_id=sid, retrieved_at=dt.datetime.now(dt.timezone.utc))


def _team(db_session, tid: str) -> Team:
    team = Team(canonical_team_id=tid, current_name=tid, source_provider="prov", source_record_id=tid,
                retrieved_at=dt.datetime.now(dt.timezone.utc))
    db_session.add(team)
    db_session.commit()
    return team


def _fixture(competition, season, home, away, idx, **result_kwargs) -> tuple[Fixture, Result]:
    native = f"{competition.canonical_competition_id}:{idx}"
    fixture = Fixture(
        canonical_fixture_id=native, competition_id=competition.id, season_id=season.id,
        home_team_id=home.id, away_team_id=away.id, status=FixtureStatus.COMPLETED,
        kickoff_utc=dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(days=idx),
        source_provider="prov", source_record_id=native, retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    result = Result(
        home_goals=result_kwargs.get("home_goals", 1), away_goals=result_kwargs.get("away_goals", 1),
        home_goals_first_half=result_kwargs.get("home_goals_first_half"),
        away_goals_first_half=result_kwargs.get("away_goals_first_half"),
        source_provider="prov", source_record_id=native, retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    return fixture, result


def _seed_league(db_session, n_matches=12, with_first_half=True):
    competition = _competition("prov:C1")
    db_session.add(competition)
    db_session.commit()
    season = _season(competition, "2025")
    db_session.add(season)
    db_session.commit()
    a, b = _team(db_session, "prov:A"), _team(db_session, "prov:B")

    fixtures = []
    for i in range(n_matches):
        home, away = (a, b) if i % 2 == 0 else (b, a)
        kwargs = dict(home_goals=2, away_goals=1)
        if with_first_half:
            kwargs.update(home_goals_first_half=1, away_goals_first_half=0)
        fixture, result = _fixture(competition, season, home, away, i, **kwargs)
        db_session.add(fixture)
        db_session.flush()
        result.fixture_id = fixture.id
        db_session.add(result)
        fixtures.append(fixture)
    db_session.commit()
    return competition, season, a, b, fixtures


def _add_stat(db_session, fixture, team, stat_name, value):
    db_session.add(MatchStatistic(
        fixture_id=fixture.id, team_id=team.id, stat_name=stat_name, stat_value=value,
        source_provider="prov", source_record_id=f"{fixture.id}:{team.id}:{stat_name}",
        retrieved_at=dt.datetime.now(dt.timezone.utc),
    ))


def test_first_half_model_enabled_with_enough_data(db_session):
    competition, season, a, b, fixtures = _seed_league(db_session, n_matches=12)
    settings = Settings(min_matches_for_model_fit=10)

    result = MarketModelTrainingService(db_session, settings).train_first_half(competition)

    assert result.version is not None
    assert result.n_matches == 12
    mv = db_session.query(ModelVersion).filter_by(model_name=FIRST_HALF_MODEL, competition_id=competition.id).one()
    assert mv.status == ModelStatus.ENABLED
    assert set(mv.parameters["attack"]) == {"prov:A", "prov:B"}


def test_first_half_model_disabled_when_half_time_scores_missing(db_session):
    competition, season, a, b, fixtures = _seed_league(db_session, n_matches=12, with_first_half=False)
    settings = Settings(min_matches_for_model_fit=10)

    result = MarketModelTrainingService(db_session, settings).train_first_half(competition)

    assert result.version is None
    assert result.n_matches == 0
    assert result.skipped_reason  # some human-readable reason was recorded
    mv = db_session.query(ModelVersion).filter_by(model_name=FIRST_HALF_MODEL, competition_id=competition.id).one()
    assert mv.status == ModelStatus.DISABLED
    assert mv.disabled_reason == result.skipped_reason


def test_corners_model_uses_match_statistics(db_session):
    competition, season, a, b, fixtures = _seed_league(db_session, n_matches=12)
    for i, fixture in enumerate(fixtures):
        home_team = a if i % 2 == 0 else b
        away_team = b if i % 2 == 0 else a
        _add_stat(db_session, fixture, home_team, "corners", 6)
        _add_stat(db_session, fixture, away_team, "corners", 4)
    db_session.commit()

    result = MarketModelTrainingService(db_session, Settings(min_matches_for_model_fit=10)).train_corners(competition)

    assert result.version is not None
    mv = db_session.query(ModelVersion).filter_by(model_name=CORNERS_MODEL, competition_id=competition.id).one()
    assert mv.hyperparameters["use_dc_adjustment"] is False


def test_corners_model_skips_fixtures_with_partial_statistics(db_session):
    competition, season, a, b, fixtures = _seed_league(db_session, n_matches=12)
    # Only give corner stats to ONE team per fixture — the fixture should be excluded entirely.
    for i, fixture in enumerate(fixtures):
        _add_stat(db_session, fixture, a, "corners", 6)
    db_session.commit()

    result = MarketModelTrainingService(db_session, Settings(min_matches_for_model_fit=10)).train_corners(competition)

    assert result.n_matches == 0
    assert result.version is None


def test_cards_model_combines_yellow_and_red(db_session):
    competition, season, a, b, fixtures = _seed_league(db_session, n_matches=12)
    for i, fixture in enumerate(fixtures):
        home_team = a if i % 2 == 0 else b
        away_team = b if i % 2 == 0 else a
        _add_stat(db_session, fixture, home_team, "yellow_cards", 2)
        _add_stat(db_session, fixture, home_team, "red_cards", 0)
        _add_stat(db_session, fixture, away_team, "yellow_cards", 1)
        _add_stat(db_session, fixture, away_team, "red_cards", 1)
    db_session.commit()

    result = MarketModelTrainingService(db_session, Settings(min_matches_for_model_fit=10)).train_cards(competition)

    assert result.version is not None
    mv = db_session.query(ModelVersion).filter_by(model_name=CARDS_MODEL, competition_id=competition.id).one()
    assert mv.status == ModelStatus.ENABLED
