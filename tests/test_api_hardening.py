"""Phase 12 hardening tests: the production startup safety check, graceful
degradation of /system-health on a database failure, login rate limiting,
and CORS. Uses the same StaticPool in-memory pattern as test_api_rbac.py."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database.models  # noqa: F401 registers all tables
import app.api.main as main_module
from app.api.main import _check_production_safety, app
from app.config import Settings
from app.database.base import Base, get_db
from app.database.models.audit import User
from app.database.models.enums import UserRole
from app.services.auth import hash_password


def test_production_safety_check_passes_in_development():
    _check_production_safety(Settings(environment="development", secret_key="change-me-in-production"))


def test_production_safety_check_rejects_default_secret_in_production():
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        _check_production_safety(Settings(environment="production", secret_key="change-me-in-production"))


def test_production_safety_check_passes_with_a_real_secret_in_production():
    _check_production_safety(Settings(environment="production", secret_key="a-real-generated-secret"))


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
    session.commit()
    session.close()

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def test_system_health_does_not_require_auth_and_reports_ok(client):
    r = client.get("/system-health")
    assert r.status_code == 200
    assert r.json()["status"] == "OK"


def test_system_health_degrades_gracefully_on_database_failure(client):
    from sqlalchemy.exc import SQLAlchemyError

    def _broken_get_db():
        class _BrokenSession:
            def query(self, *a, **k):
                raise SQLAlchemyError("simulated outage")

        yield _BrokenSession()

    app.dependency_overrides[get_db] = _broken_get_db

    r = client.get("/system-health")

    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ERROR"
    assert body["detail"] == "database unreachable"
    assert body["competitions_total"] == 0


def test_login_is_rate_limited_after_repeated_failures(client):
    settings = Settings(login_rate_limit_attempts=3, login_rate_limit_window_seconds=60)
    main_module._login_limiter = main_module.RateLimiter(
        settings.login_rate_limit_attempts, settings.login_rate_limit_window_seconds
    )
    try:
        for _ in range(3):
            r = client.post("/auth/token", data={"username": "admin@example.com", "password": "wrong"})
            assert r.status_code == 401

        r = client.post("/auth/token", data={"username": "admin@example.com", "password": "wrong"})
        assert r.status_code == 429
    finally:
        main_module._login_limiter = None


def test_successful_login_resets_the_rate_limit(client):
    main_module._login_limiter = main_module.RateLimiter(max_attempts=2, window_seconds=60)
    try:
        client.post("/auth/token", data={"username": "admin@example.com", "password": "wrong"})
        r = client.post("/auth/token", data={"username": "admin@example.com", "password": "adminpass"})
        assert r.status_code == 200

        # The successful login above reset the counter, so this fresh
        # attempt should not be blocked despite being the 3rd call overall.
        r2 = client.post("/auth/token", data={"username": "admin@example.com", "password": "wrong"})
        assert r2.status_code == 401
    finally:
        main_module._login_limiter = None


def test_cors_is_closed_by_default(client):
    """cors_allowed_origins defaults to [], so no CORSMiddleware is even
    installed — a cross-origin browser request gets no
    Access-Control-Allow-Origin header, the secure default for an API with
    no first-party frontend of its own."""
    r = client.options(
        "/competitions",
        headers={"Origin": "https://example.com", "Access-Control-Request-Method": "GET"},
    )
    assert "access-control-allow-origin" not in {k.lower() for k in r.headers.keys()}


def test_request_logging_middleware_sets_request_id_header(client):
    r = client.get("/system-health")
    assert "x-request-id" in {k.lower() for k in r.headers.keys()}
