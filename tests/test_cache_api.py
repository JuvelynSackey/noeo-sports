"""API-level tests for Redis caching (section 22): GET /competitions and
GET /predictions/{fixture} are cached, and POST /sync / POST /forecast
invalidate the relevant keys. Same "install a fakeredis-backed Cache onto
the already-started app module" technique as test_job_api.py, for the same
lru_cache-singleton reason."""
import datetime as dt

import fakeredis
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.main as main_module
import app.database.models  # noqa: F401 registers all tables
from app.api.main import app
from app.config import Settings
from app.database.base import Base, get_db
from app.database.models.audit import User
from app.database.models.competitions import Competition
from app.database.models.enums import UserRole
from app.services.auth import hash_password
from app.services.cache import Cache


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
    session.add(User(email="admin@example.com", hashed_password=hash_password("adminpass"), role=UserRole.ADMIN))
    session.add(User(email="viewer@example.com", hashed_password=hash_password("viewerpass"), role=UserRole.VIEWER))
    session.add(
        Competition(
            canonical_competition_id="prov:CACHE", name="Cache League", source_provider="prov",
            source_record_id="CACHE", retrieved_at=dt.datetime.now(dt.timezone.utc),
        )
    )
    session.commit()
    session.close()

    with TestClient(app) as test_client:
        fake_cache = Cache(Settings(redis_url="redis://localhost:6379/0"))
        fake_cache._client = fakeredis.FakeRedis(decode_responses=True)
        main_module.get_cache = lambda: fake_cache
        yield test_client, fake_cache, session_factory

    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _token(test_client: TestClient, email: str, password: str) -> str:
    r = test_client.post("/auth/token", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_competitions_list_is_cached_after_first_read(client):
    test_client, fake_cache, session_factory = client
    token = _token(test_client, "viewer@example.com", "viewerpass")

    assert fake_cache.get_json("cache:competitions") is None
    r1 = test_client.get("/competitions", headers=_auth(token))
    assert r1.status_code == 200
    assert len(r1.json()) == 1
    assert fake_cache.get_json("cache:competitions") is not None

    # Mutate the DB directly, bypassing the API — a cache hit should still
    # reflect the now-stale cached value until something invalidates it.
    session = session_factory()
    session.add(
        Competition(
            canonical_competition_id="prov:CACHE2", name="Second League", source_provider="prov",
            source_record_id="CACHE2", retrieved_at=dt.datetime.now(dt.timezone.utc),
        )
    )
    session.commit()
    session.close()

    r2 = test_client.get("/competitions", headers=_auth(token))
    assert len(r2.json()) == 1  # served from cache, not re-queried


def test_sync_invalidates_the_competitions_cache(client, monkeypatch):
    test_client, fake_cache, session_factory = client
    token = _token(test_client, "admin@example.com", "adminpass")

    test_client.get("/competitions", headers=_auth(token))
    assert fake_cache.get_json("cache:competitions") is not None

    monkeypatch.setattr(main_module, "get_provider", lambda settings: __import__(
        "app.data.providers.mock_provider", fromlist=["MockProvider"]
    ).MockProvider())

    r = test_client.post("/sync", headers=_auth(token))
    assert r.status_code == 200
    assert fake_cache.get_json("cache:competitions") is None


def test_predictions_are_cached_and_invalidated_by_a_new_forecast(client):
    from app.database.models.competitions import Season
    from app.database.models.enums import FixtureStatus, ModelStatus
    from app.database.models.fixtures import Fixture
    from app.database.models.modeling import ModelVersion
    from app.database.models.predictions import Prediction
    from app.database.models.teams import Team

    test_client, fake_cache, session_factory = client
    session = session_factory()
    competition = session.query(Competition).filter_by(canonical_competition_id="prov:CACHE").one()
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
        model_name="dixon_coles", version="cacheapi-v1", status=ModelStatus.ENABLED, competition_id=competition.id,
        trained_at=dt.datetime.now(dt.timezone.utc), hyperparameters={},
        parameters={"attack": {"prov:A": 0.1, "prov:B": -0.1}, "defence": {"prov:A": 0.0, "prov:B": 0.0},
                    "home_advantage": 0.2, "rho": 0.0, "team_ids": ["prov:A", "prov:B"]},
        evaluation_metrics={"log_likelihood": -1.0, "aic": 2.0, "n_matches": 1, "n_params": 1, "converged": True},
        is_reproducible=True,
    )
    session.add(champion)
    session.commit()
    fixture = Fixture(
        canonical_fixture_id="prov:CACHE:F1", competition_id=competition.id, season_id=season.id,
        home_team_id=a.id, away_team_id=b.id, status=FixtureStatus.SCHEDULED,
        source_provider="prov", source_record_id="CACHE:F1", retrieved_at=dt.datetime.now(dt.timezone.utc),
    )
    session.add(fixture)
    session.commit()
    session.add(
        Prediction(
            fixture_id=fixture.id, model_version_id=champion.id, dataset_version="v", feature_version="v",
            software_version="v", score_matrix={}, expected_goals_home=1.0, expected_goals_away=1.0,
            outcome_probabilities={"home_win": 0.4, "draw": 0.3, "away_win": 0.3},
        )
    )
    session.commit()
    session.close()

    token = _token(test_client, "viewer@example.com", "viewerpass")
    cache_key = "cache:predictions:prov:CACHE:F1"

    assert fake_cache.get_json(cache_key) is None
    r1 = test_client.get("/predictions/prov:CACHE:F1", headers=_auth(token))
    assert r1.status_code == 200
    assert fake_cache.get_json(cache_key) is not None

    r2 = test_client.post("/forecast", headers=_auth(token), params={"fixture": "prov:CACHE:F1"})
    assert r2.status_code == 200
    assert fake_cache.get_json(cache_key) is None  # invalidated by the new forecast
