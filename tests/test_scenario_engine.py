import datetime as dt

import pytest

from app.config import Settings
from app.database.models.enums import FixtureStatus
from app.database.models.modeling import ModelVersion
from app.database.models.predictions import Prediction, ScenarioPrediction
from app.services.scenario_engine import LABEL, ScenarioAssumptions, ScenarioEngine, ScenarioValidationError
from tests.test_forecast_service import _competition, _fixture, _model_version, _season, _team


def _setup(db_session):
    competition = _competition("prov:SCEN")
    db_session.add(competition)
    db_session.commit()
    season = _season(competition, "2025")
    db_session.add(season)
    db_session.commit()
    a = _team(db_session, "prov:A")
    b = _team(db_session, "prov:B")
    champion = _model_version(
        competition, "dixon_coles", {a.canonical_team_id: 0.5, b.canonical_team_id: -0.5},
        {a.canonical_team_id: 0.0, b.canonical_team_id: 0.0}, home_advantage=0.3, rho=-0.1,
    )
    db_session.add(champion)
    db_session.commit()
    fixture = _fixture(competition, season, a, b, "F1", status=FixtureStatus.SCHEDULED)
    db_session.add(fixture)
    db_session.commit()
    return competition, season, a, b, champion, fixture


def _add_baseline(db_session, fixture, champion):
    prediction = Prediction(
        fixture_id=fixture.id, model_version_id=champion.id, dataset_version="v", feature_version="v",
        software_version="v", score_matrix={"matrix": [[0.5, 0.2], [0.2, 0.1]]},
        expected_goals_home=1.4, expected_goals_away=1.1,
        outcome_probabilities={"home_win": 0.45, "draw": 0.28, "away_win": 0.27},
    )
    db_session.add(prediction)
    db_session.commit()
    return prediction


def test_run_raises_without_a_baseline_forecast(db_session):
    competition, season, a, b, champion, fixture = _setup(db_session)

    with pytest.raises(ScenarioValidationError, match="no baseline forecast"):
        ScenarioEngine(db_session).run(fixture, "no baseline yet", ScenarioAssumptions())


def test_run_rejects_a_team_not_in_the_fixture(db_session):
    competition, season, a, b, champion, fixture = _setup(db_session)
    _add_baseline(db_session, fixture, champion)

    with pytest.raises(ScenarioValidationError, match="not one of this fixture's teams"):
        ScenarioEngine(db_session).run(
            fixture, "bad team", ScenarioAssumptions(attack_delta={"prov:GHOST": 0.5})
        )


def test_run_rejects_a_delta_beyond_the_configured_bound(db_session):
    settings = Settings(scenario_max_abs_delta=1.0)
    competition, season, a, b, champion, fixture = _setup(db_session)
    _add_baseline(db_session, fixture, champion)

    with pytest.raises(ScenarioValidationError, match=r"\+/-1\.0"):
        ScenarioEngine(db_session, settings).run(
            fixture, "too extreme", ScenarioAssumptions(attack_delta={a.canonical_team_id: 5.0})
        )


def test_run_computes_and_persists_a_hypothetical_result(db_session):
    competition, season, a, b, champion, fixture = _setup(db_session)
    baseline = _add_baseline(db_session, fixture, champion)

    record = ScenarioEngine(db_session).run(
        fixture, "A loses its striker", ScenarioAssumptions(attack_delta={a.canonical_team_id: -1.0}), requested_by="analyst@example.com"
    )

    assert isinstance(record, ScenarioPrediction)
    assert record.scenario_name == "A loses its striker"
    assert record.baseline_prediction_id == baseline.id
    assert record.requested_by == "analyst@example.com"
    assert record.assumptions["attack_delta"] == {a.canonical_team_id: -1.0}
    assert "expected_goals_home" in record.scenario_result
    assert "outcome_probabilities" in record.scenario_result
    # A's attack strength was weakened -> A's expected goals should drop
    # relative to the baseline's own expected goals.
    assert record.scenario_result["expected_goals_home"] < baseline.expected_goals_home
    assert record.difference["expected_goals_home"] < 0

    stored = db_session.query(ScenarioPrediction).filter_by(fixture_id=fixture.id).one()
    assert stored.id == record.id


def test_scenario_never_mutates_the_baseline_prediction(db_session):
    competition, season, a, b, champion, fixture = _setup(db_session)
    baseline = _add_baseline(db_session, fixture, champion)
    original_home_goals = baseline.expected_goals_home

    ScenarioEngine(db_session).run(
        fixture, "big swing", ScenarioAssumptions(attack_delta={a.canonical_team_id: 2.0})
    )

    db_session.refresh(baseline)
    assert baseline.expected_goals_home == original_home_goals


def test_scenario_never_mutates_the_champion_model_parameters(db_session):
    competition, season, a, b, champion, fixture = _setup(db_session)
    _add_baseline(db_session, fixture, champion)
    original_attack = dict(champion.parameters["attack"])

    ScenarioEngine(db_session).run(
        fixture, "big swing", ScenarioAssumptions(attack_delta={a.canonical_team_id: 2.0})
    )

    db_session.refresh(champion)
    assert champion.parameters["attack"] == original_attack


def test_result_is_always_labelled_hypothetical():
    assert LABEL == "HYPOTHETICAL"
