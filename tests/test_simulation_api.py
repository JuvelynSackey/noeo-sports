"""API-level tests for the Monte Carlo simulation endpoints (section 42)."""
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
from app.database.models.enums import FixtureStatus, ModelStatus, SeasonStatus, UserRole
from app.database.models.fixtures import Fixture
from app.database.models.modeling import ModelVersion
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
        canonical_competition_id="prov:SIMAPI", name="Sim League", source_provider="prov",
        source_record_id="SIMAPI", retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    session.add(competition)
    session.commit()
    season = Season(
        competition_id=competition.id, canonical_season_id="2026", name="2026", status=SeasonStatus.ACTIVE,
        source_provider="prov", source_record_id="2026", retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    session.add(season)
    a = Team(canonical_team_id="prov:A", current_name="A", source_provider="prov", source_record_id="A",
              retrieved_at=dt.datetime.now(dt.timezone.utc))
    b = Team(canonical_team_id="prov:B", current_name="B", source_provider="prov", source_record_id="B",
              retrieved_at=dt.datetime.now(dt.timezone.utc))
    session.add_all([a, b])
    session.commit()
    session.add(
        ModelVersion(
            model_name="dixon_coles", version="simapi-v1", status=ModelStatus.ENABLED, competition_id=competition.id,
            trained_at=dt.datetime.now(dt.timezone.utc), hyperparameters={},
            parameters={"attack": {"prov:A": 0.5, "prov:B": -0.5}, "defence": {"prov:A": 0.0, "prov:B": 0.0},
                        "home_advantage": 0.2, "rho": 0.0, "team_ids": ["prov:A", "prov:B"]},
            evaluation_metrics={"log_likelihood": -1.0, "aic": 2.0, "n_matches": 1, "n_params": 1, "converged": True},
            is_reproducible=True,
        )
    )
    session.add(
        Fixture(
            canonical_fixture_id="prov:SIMAPI:F1", competition_id=competition.id, season_id=season.id,
            home_team_id=a.id, away_team_id=b.id, status=FixtureStatus.SCHEDULED,
            source_provider="prov", source_record_id="SIMAPI:F1", retrieved_at=dt.datetime.now(dt.timezone.utc),
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


def test_run_simulation_returns_standings_for_both_teams(client):
    token = _token(client)
    r = client.post("/simulations", headers=_auth(token), params={"competition": "prov:SIMAPI", "n_simulations": 200, "random_seed": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["n_simulations"] == 200
    assert body["random_seed"] == 1
    assert len(body["standings"]) == 2
    total_title_prob = sum(s["title_probability"] for s in body["standings"])
    assert abs(total_title_prob - 1.0) < 1e-9


def test_run_simulation_requires_auth(client):
    r = client.post("/simulations", params={"competition": "prov:SIMAPI"})
    assert r.status_code == 401


def test_run_simulation_unknown_competition_is_404(client):
    token = _token(client)
    r = client.post("/simulations", headers=_auth(token), params={"competition": "prov:NOPE"})
    assert r.status_code == 404


def test_get_simulation_by_scenario_id(client):
    token = _token(client)
    r = client.post("/simulations", headers=_auth(token), params={"competition": "prov:SIMAPI", "n_simulations": 100, "random_seed": 2})
    scenario_id = r.json()["scenario_id"]

    r2 = client.get(f"/simulations/{scenario_id}", headers=_auth(token))
    assert r2.status_code == 200
    assert r2.json()["scenario_id"] == scenario_id


def test_get_unknown_simulation_is_404(client):
    token = _token(client)
    r = client.get("/simulations/does-not-exist", headers=_auth(token))
    assert r.status_code == 404


def test_list_simulations_filters_by_competition(client):
    token = _token(client)
    client.post("/simulations", headers=_auth(token), params={"competition": "prov:SIMAPI", "n_simulations": 50})

    r = client.get("/simulations", headers=_auth(token), params={"competition": "prov:SIMAPI"})
    assert r.status_code == 200
    assert len(r.json()) == 1

    r2 = client.get("/simulations", headers=_auth(token))
    assert r2.status_code == 200
    assert len(r2.json()) == 1


def test_conformal_endpoint_empty_without_calibration(client):
    token = _token(client)
    r = client.get("/conformal", headers=_auth(token), params={"competition": "prov:SIMAPI"})
    assert r.status_code == 200
    assert r.json() == []


def test_conformal_endpoint_requires_auth(client):
    r = client.get("/conformal")
    assert r.status_code == 401
