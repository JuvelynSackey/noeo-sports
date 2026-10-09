import datetime as dt

import pytest

from app.database.models.enums import FixtureStatus, SeasonStatus
from app.database.models.fixtures import Result
from app.database.models.modeling import ModelVersion
from app.database.models.simulation import SimulationRun, SimulationStandingResult
from app.services.simulation import SeasonSimulationService
from tests.test_forecast_service import _competition, _fixture, _model_version, _team


def _active_season(db_session, competition, sid="2026"):
    from app.database.models.competitions import Season

    season = Season(
        competition_id=competition.id, canonical_season_id=sid, name=sid, status=SeasonStatus.ACTIVE,
        source_provider="prov", source_record_id=sid, retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    db_session.add(season)
    db_session.commit()
    return season


def _complete(db_session, competition, season, home, away, native_id, hg, ag):
    fixture = _fixture(competition, season, home, away, native_id, status=FixtureStatus.COMPLETED)
    db_session.add(fixture)
    db_session.flush()
    db_session.add(
        Result(fixture_id=fixture.id, home_goals=hg, away_goals=ag, source_provider="prov",
               source_record_id=native_id, retrieved_at=dt.datetime.now(dt.timezone.utc))
    )
    db_session.commit()
    return fixture


def _setup_two_team_league(db_session):
    competition = _competition("prov:SIM")
    db_session.add(competition)
    db_session.commit()
    season = _active_season(db_session, competition)
    a = _team(db_session, "prov:A")
    b = _team(db_session, "prov:B")
    return competition, season, a, b


def test_simulate_skips_without_active_season(db_session):
    competition = _competition("prov:NOSEASON")
    db_session.add(competition)
    db_session.commit()

    report = SeasonSimulationService(db_session).simulate(competition)

    assert not report.completed
    assert "no active season" in report.skipped_reason


def test_simulate_skips_without_enabled_dixon_coles(db_session):
    competition, season, a, b = _setup_two_team_league(db_session)
    db_session.add(_fixture(competition, season, a, b, "F1"))
    db_session.commit()

    report = SeasonSimulationService(db_session).simulate(competition)

    assert not report.completed
    assert "dixon_coles" in report.skipped_reason


def test_simulate_skips_with_no_remaining_fixtures(db_session):
    competition, season, a, b = _setup_two_team_league(db_session)
    db_session.add(_model_version(competition, "dixon_coles", {a.canonical_team_id: 0.1, b.canonical_team_id: -0.1},
                                   {a.canonical_team_id: 0.0, b.canonical_team_id: 0.0}))
    db_session.commit()
    _complete(db_session, competition, season, a, b, "F1", 2, 0)

    report = SeasonSimulationService(db_session).simulate(competition)

    assert not report.completed
    assert "no remaining fixtures" in report.skipped_reason


def test_simulate_is_deterministic_given_the_same_seed(db_session):
    competition, season, a, b = _setup_two_team_league(db_session)
    db_session.add(_model_version(competition, "dixon_coles", {a.canonical_team_id: 1.2, b.canonical_team_id: -1.2},
                                   {a.canonical_team_id: 0.0, b.canonical_team_id: 0.0}))
    db_session.commit()
    db_session.add(_fixture(competition, season, a, b, "F1"))
    db_session.commit()

    service = SeasonSimulationService(db_session)
    report1 = service.simulate(competition, season, n_simulations=500, random_seed=42)
    report2 = service.simulate(competition, season, n_simulations=500, random_seed=42)

    by_team_1 = {s.team_canonical_id: s for s in report1.standings}
    by_team_2 = {s.team_canonical_id: s for s in report2.standings}
    for team_id in by_team_1:
        assert by_team_1[team_id].title_probability == by_team_2[team_id].title_probability
        assert by_team_1[team_id].mean_points == by_team_2[team_id].mean_points


def test_simulate_favors_the_stronger_team_and_probabilities_sum_to_one(db_session):
    competition, season, a, b = _setup_two_team_league(db_session)
    # A is overwhelmingly stronger than B.
    db_session.add(_model_version(competition, "dixon_coles", {a.canonical_team_id: 2.0, b.canonical_team_id: -2.0},
                                   {a.canonical_team_id: -1.0, b.canonical_team_id: 1.0}, rho=0.0))
    db_session.commit()
    db_session.add(_fixture(competition, season, a, b, "F1"))
    db_session.commit()

    report = SeasonSimulationService(db_session).simulate(competition, season, n_simulations=2000, random_seed=7)

    assert report.completed
    assert report.n_remaining_fixtures == 1
    assert report.n_unscoreable_fixtures == 0

    standings = {s.team_canonical_id: s for s in report.standings}
    assert standings[a.canonical_team_id].title_probability > 0.9
    assert standings[a.canonical_team_id].title_probability + standings[b.canonical_team_id].title_probability == 1.0

    for s in report.standings:
        total_prob = sum(s.position_probabilities.values())
        assert total_prob == pytest.approx(1.0)


def test_simulate_persists_run_and_standings(db_session):
    competition, season, a, b = _setup_two_team_league(db_session)
    db_session.add(_model_version(competition, "dixon_coles", {a.canonical_team_id: 0.3, b.canonical_team_id: -0.3},
                                   {a.canonical_team_id: 0.0, b.canonical_team_id: 0.0}))
    db_session.commit()
    _complete(db_session, competition, season, a, b, "F1", 1, 1)
    db_session.add(_fixture(competition, season, b, a, "F2"))
    db_session.commit()

    report = SeasonSimulationService(db_session).simulate(competition, season, n_simulations=100, random_seed=1)

    run = db_session.query(SimulationRun).filter_by(scenario_id=report.scenario_id).one()
    assert run.n_simulations == 100
    assert run.random_seed == 1
    assert run.competition_id == competition.id
    assert run.season_id == season.id
    assert run.n_remaining_fixtures == 1
    assert run.input_snapshot["standings_before_simulation"]

    standing_rows = db_session.query(SimulationStandingResult).filter_by(simulation_run_id=run.id).all()
    assert len(standing_rows) == 2


def test_simulate_records_unscoreable_fixtures_without_crashing(db_session):
    competition, season, a, b = _setup_two_team_league(db_session)
    c = _team(db_session, "prov:C")
    db_session.add(_model_version(competition, "dixon_coles", {a.canonical_team_id: 0.1, b.canonical_team_id: -0.1},
                                   {a.canonical_team_id: 0.0, b.canonical_team_id: 0.0}))
    db_session.commit()
    db_session.add(_fixture(competition, season, a, b, "F1"))
    # C never appears in the trained model's parameters, so this fixture can't be scored.
    db_session.add(_fixture(competition, season, a, c, "F2"))
    db_session.commit()

    report = SeasonSimulationService(db_session).simulate(competition, season, n_simulations=100, random_seed=1)

    assert report.completed
    assert report.n_remaining_fixtures == 2
    assert report.n_unscoreable_fixtures == 1


def test_random_seed_is_generated_and_recorded_when_not_supplied(db_session):
    competition, season, a, b = _setup_two_team_league(db_session)
    db_session.add(_model_version(competition, "dixon_coles", {a.canonical_team_id: 0.1, b.canonical_team_id: -0.1},
                                   {a.canonical_team_id: 0.0, b.canonical_team_id: 0.0}))
    db_session.commit()
    db_session.add(_fixture(competition, season, a, b, "F1"))
    db_session.commit()

    report = SeasonSimulationService(db_session).simulate(competition, season, n_simulations=50)

    assert report.random_seed is not None
    run = db_session.query(SimulationRun).filter_by(scenario_id=report.scenario_id).one()
    assert run.random_seed == report.random_seed
