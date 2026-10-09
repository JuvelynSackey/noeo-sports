"""API-level tests for the scenario engine endpoints (section 59)."""
import datetime as dt

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database.models  # noqa: F401 registers all tables
from app.api.main import app
from app.database.base import Base, get_db
from app.database.models.audit import User
from app.database.models.competitions import Competition, Season
from app.database.models.enums import FixtureStatus, ModelStatus, UserRole
from app.database.models.fixtures import Fixture
from app.database.models.modeling import ModelVersion
from app.database.models.predictions import Prediction
from app.database.models.teams import Team
from app.services.auth import hash_password


@pytest.fixture()
def client():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, future=True)

    def _override_get_db():
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db

    session = session_factory()
    session.add(User(email="viewer@example.com", hashed_password=hash_password("viewerpass"), role=UserRole.VIEWER))

    competition = Competition(
        canonical_competition_id="prov:SCENAPI", name="Scenario League", source_provider="prov",
        source_record_id="SCENAPI", retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    session.add(competition)
    session.commit()
    season = Season(
        competition_id=competition.id, canonical_season_id="2026", name="2026",
        source_provider="prov", source_record_id="2026", retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    session.add(season)
    a = Team(canonical_team_id="prov:A", current_name="A", source_provider="prov", source_record_id="A",
              retrieved_at=dt.datetime.now(dt.timezone.utc))
    b = Team(canonical_team_id="prov:B", current_name="B", source_provider="prov", source_record_id="B",
              retrieved_at=dt.datetime.now(dt.timezone.utc))
    session.add_all([a, b])
    session.commit()
    champion = ModelVersion(
        model_name="dixon_coles", version="scenapi-v1", status=ModelStatus.ENABLED, competition_id=competition.id,
        trained_at=dt.datetime.now(dt.timezone.utc), hyperparameters={},
        parameters={"attack": {"prov:A": 0.5, "prov:B": -0.5}, "defence": {"prov:A": 0.0, "prov:B": 0.0},
                    "home_advantage": 0.2, "rho": 0.0, "team_ids": ["prov:A", "prov:B"]},
        evaluation_metrics={"log_likelihood": -1.0, "aic": 2.0, "n_matches": 1, "n_params": 1, "converged": True},
        is_reproducible=True,
    )
    session.add(champion)
    session.commit()
    fixture = Fixture(
        canonical_fixture_id="prov:SCENAPI:F1", competition_id=competition.id, season_id=season.id,
        home_team_id=a.id, away_team_id=b.id, status=FixtureStatus.SCHEDULED,
        source_provider="prov", source_record_id="SCENAPI:F1", retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    session.add(fixture)
    session.commit()
    session.add(
        Prediction(
            fixture_id=fixture.id, model_version_id=champion.id, dataset_version="v", feature_version="v",
            software_version="v", score_matrix={"matrix": [[0.5, 0.2], [0.2, 0.1]]},
            expected_goals_home=1.4, expected_goals_away=1.1,
            outcome_probabilities={"home_win": 0.45, "draw": 0.28, "away_win": 0.27},
        )
    )
    session.commit()
    session.close()

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _token(client: TestClient) -> str:
    r = client.post("/auth/token", data={"username": "viewer@example.com", "password": "viewerpass"})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_run_scenario_returns_a_hypothetical_result(client):
    token = _token(client)
    r = client.post(
        "/scenarios",
        headers=_auth(token),
        params={"fixture": "prov:SCENAPI:F1"},
        json={"scenario_name": "A loses its striker", "attack_delta": {"prov:A": -1.0}},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["label"] == "HYPOTHETICAL"
    assert body["scenario_name"] == "A loses its striker"
    assert body["fixture_canonical_id"] == "prov:SCENAPI:F1"
    assert body["scenario_result"]["expected_goals_home"] < 1.4
    assert body["difference"]["expected_goals_home"] < 0
    assert body["requested_by"] == "viewer@example.com"


def test_run_scenario_requires_auth(client):
    r = client.post("/scenarios", params={"fixture": "prov:SCENAPI:F1"}, json={"scenario_name": "x"})
    assert r.status_code == 401


def test_run_scenario_unknown_fixture_is_404(client):
    token = _token(client)
    r = client.post("/scenarios", headers=_auth(token), params={"fixture": "prov:NOPE"}, json={"scenario_name": "x"})
    assert r.status_code == 404


def test_run_scenario_rejects_unknown_team(client):
    token = _token(client)
    r = client.post(
        "/scenarios", headers=_auth(token), params={"fixture": "prov:SCENAPI:F1"},
        json={"scenario_name": "x", "attack_delta": {"prov:GHOST": 1.0}},
    )
    assert r.status_code == 422


def test_list_scenarios_returns_prior_runs(client):
    token = _token(client)
    client.post(
        "/scenarios", headers=_auth(token), params={"fixture": "prov:SCENAPI:F1"},
        json={"scenario_name": "first", "home_advantage_delta": 0.1},
    )
    client.post(
        "/scenarios", headers=_auth(token), params={"fixture": "prov:SCENAPI:F1"},
        json={"scenario_name": "second", "home_advantage_delta": -0.1},
    )

    r = client.get("/scenarios/prov:SCENAPI:F1", headers=_auth(token))
    assert r.status_code == 200
    names = {s["scenario_name"] for s in r.json()}
    assert names == {"first", "second"}


def test_list_scenarios_unknown_fixture_is_404(client):
    token = _token(client)
    r = client.get("/scenarios/prov:NOPE", headers=_auth(token))
    assert r.status_code == 404
