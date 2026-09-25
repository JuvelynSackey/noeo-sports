import datetime as dt

from app.config import Settings
from app.database.models.competitions import Competition, Season
from app.database.models.fixtures import Fixture, Result
from app.database.models.league import LeagueParameter
from app.database.models.teams import Team
from app.services.league_parameters import LeagueParameterService


def _competition(cid: str) -> Competition:
    return Competition(
        canonical_competition_id=cid,
        name=cid,
        source_provider="prov",
        source_record_id=cid,
        retrieved_at=dt.datetime.now(dt.timezone.utc),
    )


def _season(competition: Competition, sid: str) -> Season:
    return Season(
        competition_id=competition.id,
        canonical_season_id=sid,
        name=sid,
        source_provider="prov",
        source_record_id=sid,
        retrieved_at=dt.datetime.now(dt.timezone.utc),
    )


def _team(db_session, tid: str) -> Team:
    team = Team(canonical_team_id=tid, current_name=tid, source_provider="prov", source_record_id=tid,
                retrieved_at=dt.datetime.now(dt.timezone.utc))
    db_session.add(team)
    db_session.commit()
    return team


def _add_result(db_session, competition, season, home, away, hg, ag, idx):
    native_id = f"{competition.canonical_competition_id}:{season.canonical_season_id}:{idx}"
    fixture = Fixture(
        canonical_fixture_id=native_id,
        competition_id=competition.id,
        season_id=season.id,
        home_team_id=home.id,
        away_team_id=away.id,
        source_provider="prov",
        source_record_id=native_id,
        retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    db_session.add(fixture)
    db_session.flush()
    db_session.add(Result(fixture_id=fixture.id, home_goals=hg, away_goals=ag, source_provider="prov",
                           source_record_id=native_id, retrieved_at=dt.datetime.now(dt.timezone.utc)))
    db_session.commit()


def test_computes_raw_stats_with_a_large_sample(db_session):
    settings = Settings(league_shrinkage_min_sample=5)
    competition = _competition("prov:C1")
    db_session.add(competition)
    db_session.commit()
    season = _season(competition, "2025")
    db_session.add(season)
    db_session.commit()
    a, b = _team(db_session, "prov:A"), _team(db_session, "prov:B")

    scores = [(2, 1), (1, 1), (3, 0), (2, 2), (1, 0), (0, 0)]
    for i, (hg, ag) in enumerate(scores):
        _add_result(db_session, competition, season, a, b, hg, ag, i)

    record = LeagueParameterService(db_session, settings).compute(competition, season)

    assert record.sample_size == 6
    assert record.shrinkage_applied is False  # 6 >= threshold of 5... wait threshold is min sample below which shrink applies
    expected_avg_home = sum(h for h, _ in scores) / len(scores)
    assert record.avg_home_goals == expected_avg_home


def test_shrinkage_pulls_small_sample_toward_global_prior(db_session):
    settings = Settings(league_shrinkage_min_sample=100, league_shrinkage_prior_strength=20)

    # A second competition with a lot of low-scoring matches establishes the global prior.
    prior_comp = _competition("prov:PRIOR")
    db_session.add(prior_comp)
    db_session.commit()
    prior_season = _season(prior_comp, "2025")
    db_session.add(prior_season)
    db_session.commit()
    pa, pb = _team(db_session, "prov:PA"), _team(db_session, "prov:PB")
    for i in range(50):
        _add_result(db_session, prior_comp, prior_season, pa, pb, 0, 0, i)

    # The target competition has just 2 high-scoring matches — a tiny, noisy sample.
    competition = _competition("prov:SMALL")
    db_session.add(competition)
    db_session.commit()
    season = _season(competition, "2025")
    db_session.add(season)
    db_session.commit()
    a, b = _team(db_session, "prov:A"), _team(db_session, "prov:B")
    _add_result(db_session, competition, season, a, b, 5, 5, 0)
    _add_result(db_session, competition, season, a, b, 5, 5, 1)

    record = LeagueParameterService(db_session, settings).compute(competition, season)

    assert record.shrinkage_applied is True
    # Raw average is 5.0; global prior average (from the 0-0 competition) is 0.0.
    # The shrunk estimate must land strictly between the two.
    assert 0.0 < record.avg_home_goals < 5.0


def test_no_results_yields_empty_record(db_session):
    competition = _competition("prov:EMPTY")
    db_session.add(competition)
    db_session.commit()
    season = _season(competition, "2025")
    db_session.add(season)
    db_session.commit()

    record = LeagueParameterService(db_session).compute(competition, season)

    assert record.sample_size == 0
    assert record.avg_home_goals is None
    assert record.shrinkage_applied is False


def test_rerun_updates_existing_record_rather_than_duplicating(db_session):
    competition = _competition("prov:C2")
    db_session.add(competition)
    db_session.commit()
    season = _season(competition, "2025")
    db_session.add(season)
    db_session.commit()
    a, b = _team(db_session, "prov:A"), _team(db_session, "prov:B")
    _add_result(db_session, competition, season, a, b, 1, 1, 0)

    service = LeagueParameterService(db_session, Settings(league_shrinkage_min_sample=1))
    service.compute(competition, season)
    _add_result(db_session, competition, season, a, b, 3, 0, 1)
    service.compute(competition, season)

    assert db_session.query(LeagueParameter).filter_by(competition_id=competition.id, season_id=season.id).count() == 1
