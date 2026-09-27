import datetime as dt

from app.config import Settings
from app.database.models.enums import FixtureStatus, ModelStatus
from app.database.models.fixtures import Result
from app.database.models.modeling import ModelVersion
from app.models.goal_model import GoalModelFit
from app.services.champion_challenger import ChampionChallengerService, get_champion, split_by_champion_cutoff
from tests.test_forecast_service import _competition, _fixture, _model_version, _season, _team


def _fit(attack: dict, defence: dict, home_advantage: float = 0.3, rho: float = -0.1) -> GoalModelFit:
    return GoalModelFit(
        team_ids=list(attack), attack=attack, defence=defence, home_advantage=home_advantage, rho=rho,
        converged=True, log_likelihood=-10.0, aic=20.0, n_matches=20, n_params=5,
    )


def _setup(db_session):
    competition = _competition("prov:CC")
    db_session.add(competition)
    db_session.commit()
    season = _season(competition, "2025")
    db_session.add(season)
    db_session.commit()
    a = _team(db_session, "prov:A")
    b = _team(db_session, "prov:B")
    return competition, season, a, b


def _completed_fixture(db_session, competition, season, home, away, native_id, kickoff, hg, ag):
    fixture = _fixture(competition, season, home, away, native_id, status=FixtureStatus.COMPLETED, kickoff=kickoff)
    db_session.add(fixture)
    db_session.flush()
    db_session.add(
        Result(
            fixture_id=fixture.id, home_goals=hg, away_goals=ag, source_provider="prov",
            source_record_id=native_id, retrieved_at=dt.datetime.now(dt.timezone.utc),
        )
    )
    db_session.commit()
    db_session.refresh(fixture)
    return fixture


def test_promotes_unconditionally_when_no_champion_exists(db_session):
    competition, season, a, b = _setup(db_session)
    gate = ChampionChallengerService(db_session, Settings())

    full_fit = _fit({a.canonical_team_id: 0.5, b.canonical_team_id: -0.5}, {a.canonical_team_id: 0.0, b.canonical_team_id: 0.0})
    decision = gate.evaluate_and_promote(competition, "dixon_coles", True, None, full_fit, None, [], None, None)

    assert decision.decision == "PROMOTED_NO_CHAMPION"
    assert decision.promoted
    mv = db_session.query(ModelVersion).filter_by(version=decision.version).one()
    assert mv.status == ModelStatus.ENABLED


def test_promotes_unconditionally_with_too_few_new_matches(db_session):
    competition, season, a, b = _setup(db_session)
    settings = Settings(champion_challenger_min_new_matches=5)
    cutoff = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)
    champion_mv = _model_version(
        competition, "dixon_coles", {a.canonical_team_id: 0.1}, {a.canonical_team_id: 0.0}, training_window_end=cutoff
    )
    db_session.add(champion_mv)
    db_session.commit()

    gate = ChampionChallengerService(db_session, settings)
    full_fit = _fit({a.canonical_team_id: 0.2}, {a.canonical_team_id: 0.0})
    holdout = [(a.canonical_team_id, b.canonical_team_id, 2, 0)]  # only 1, below the threshold of 5

    decision = gate.evaluate_and_promote(competition, "dixon_coles", True, champion_mv, full_fit, full_fit, holdout, cutoff, cutoff)

    assert decision.decision == "PROMOTED_INSUFFICIENT_EVIDENCE"
    assert db_session.query(ModelVersion).filter_by(version=champion_mv.version).one().status == ModelStatus.RETIRED
    assert db_session.query(ModelVersion).filter_by(version=decision.version).one().status == ModelStatus.ENABLED


def test_promotes_challenger_that_clearly_beats_champion_on_new_matches(db_session):
    competition, season, a, b = _setup(db_session)
    settings = Settings(champion_challenger_min_new_matches=3, champion_challenger_log_loss_tolerance=0.02)
    cutoff = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)

    # Champion badly favors B; the challenger correctly favors A, matching
    # what actually happened in the matches completed since the champion trained.
    champion_mv = _model_version(
        competition, "dixon_coles", {a.canonical_team_id: -1.0, b.canonical_team_id: 1.0},
        {a.canonical_team_id: 0.0, b.canonical_team_id: 0.0}, training_window_end=cutoff,
    )
    db_session.add(champion_mv)
    db_session.commit()

    challenger_fit = _fit(
        {a.canonical_team_id: 1.5, b.canonical_team_id: -1.5}, {a.canonical_team_id: 0.0, b.canonical_team_id: 0.0}
    )
    holdout = [(a.canonical_team_id, b.canonical_team_id, 3, 0) for _ in range(4)]

    gate = ChampionChallengerService(db_session, settings)
    decision = gate.evaluate_and_promote(
        competition, "dixon_coles", True, champion_mv, challenger_fit, challenger_fit, holdout, cutoff, cutoff
    )

    assert decision.decision == "PROMOTED"
    assert decision.challenger_log_loss < decision.champion_log_loss
    assert db_session.query(ModelVersion).filter_by(version=champion_mv.version).one().status == ModelStatus.RETIRED
    assert db_session.query(ModelVersion).filter_by(version=decision.version).one().status == ModelStatus.ENABLED


def test_rejects_challenger_that_is_worse_than_champion_on_new_matches(db_session):
    competition, season, a, b = _setup(db_session)
    settings = Settings(champion_challenger_min_new_matches=3, champion_challenger_log_loss_tolerance=0.02)
    cutoff = dt.datetime(2025, 1, 1, tzinfo=dt.timezone.utc)

    # Champion correctly favors A; challenger wrongly favors B.
    champion_mv = _model_version(
        competition, "dixon_coles", {a.canonical_team_id: 1.5, b.canonical_team_id: -1.5},
        {a.canonical_team_id: 0.0, b.canonical_team_id: 0.0}, training_window_end=cutoff,
    )
    db_session.add(champion_mv)
    db_session.commit()

    challenger_fit = _fit(
        {a.canonical_team_id: -1.0, b.canonical_team_id: 1.0}, {a.canonical_team_id: 0.0, b.canonical_team_id: 0.0}
    )
    holdout = [(a.canonical_team_id, b.canonical_team_id, 3, 0) for _ in range(4)]

    gate = ChampionChallengerService(db_session, settings)
    decision = gate.evaluate_and_promote(
        competition, "dixon_coles", True, champion_mv, challenger_fit, challenger_fit, holdout, cutoff, cutoff
    )

    assert decision.decision == "REJECTED"
    assert not decision.promoted
    assert decision.champion_log_loss < decision.challenger_log_loss
    champion_row = db_session.query(ModelVersion).filter_by(version=champion_mv.version).one()
    assert champion_row.status == ModelStatus.ENABLED  # unchanged, still live
    challenger_row = db_session.query(ModelVersion).filter_by(version=decision.version).one()
    assert challenger_row.status == ModelStatus.RETIRED
    assert challenger_row.disabled_reason is not None


def test_get_champion_returns_the_enabled_version_only(db_session):
    competition, season, a, b = _setup(db_session)
    retired = _model_version(competition, "dixon_coles", {a.canonical_team_id: 0.1}, {a.canonical_team_id: 0.0}, status=ModelStatus.RETIRED)
    enabled = _model_version(competition, "poisson_baseline", {a.canonical_team_id: 0.1}, {a.canonical_team_id: 0.0})
    db_session.add_all([retired, enabled])
    db_session.commit()

    assert get_champion(db_session, competition, "dixon_coles") is None
    found = get_champion(db_session, competition, "poisson_baseline")
    assert found is not None
    assert found.version == enabled.version


def test_split_by_champion_cutoff_separates_seen_from_new(db_session):
    competition, season, a, b = _setup(db_session)
    cutoff = dt.datetime(2025, 6, 1, tzinfo=dt.timezone.utc)
    champion_mv = _model_version(
        competition, "dixon_coles", {a.canonical_team_id: 0.1}, {a.canonical_team_id: 0.0}, training_window_end=cutoff
    )
    db_session.add(champion_mv)
    db_session.commit()

    old_fixture = _completed_fixture(db_session, competition, season, a, b, "OLD", cutoff - dt.timedelta(days=10), 1, 0)
    new_fixture = _completed_fixture(db_session, competition, season, a, b, "NEW", cutoff + dt.timedelta(days=10), 2, 1)
    no_kickoff_fixture = _completed_fixture(db_session, competition, season, a, b, "NOKICK", None, 0, 0)

    completed = [(old_fixture, old_fixture.result), (new_fixture, new_fixture.result), (no_kickoff_fixture, no_kickoff_fixture.result)]
    teams_by_id = {a.id: a, b.id: b}

    eval_rows, holdout = split_by_champion_cutoff(completed, teams_by_id, champion_mv)

    assert eval_rows == [(old_fixture, old_fixture.result)]
    assert holdout == [(a.canonical_team_id, b.canonical_team_id, 2, 1)]


def test_split_by_champion_cutoff_with_no_champion_treats_everything_as_seen(db_session):
    competition, season, a, b = _setup(db_session)
    fixture = _completed_fixture(db_session, competition, season, a, b, "ONLY", dt.datetime.now(dt.timezone.utc), 1, 1)
    completed = [(fixture, fixture.result)]

    eval_rows, holdout = split_by_champion_cutoff(completed, {a.id: a, b.id: b}, None)

    assert eval_rows == completed
    assert holdout == []
