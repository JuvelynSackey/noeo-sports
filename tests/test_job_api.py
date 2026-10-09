"""API-level tests for the async job queue endpoints (section 74).

Rather than fighting the several independent lru_cache-backed singletons
involved in a real Redis-enabled lifespan (get_settings, get_cache,
get_cache's own module-level cache), these directly install a
fakeredis-backed JobQueueService onto the running app module after the
TestClient's (real, Redis-disabled-by-default) lifespan has already
started — main.py's endpoint functions re-read the module-level
`_job_queue` global on every call, so this is seen immediately.
"""
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
from app.database.models.enums import UserRole
from app.services.auth import hash_password
from app.services.job_queue import JobQueueService


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
    session.commit()
    session.close()

    with TestClient(app) as test_client:
        fake_queue = JobQueueService(Settings(redis_url="redis://localhost:6379/0"))
        fake_queue._client = fakeredis.FakeRedis(decode_responses=True)
        main_module._job_queue = fake_queue
        yield test_client, fake_queue

    main_module._job_queue = None
    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _token(test_client: TestClient, email: str, password: str) -> str:
    r = test_client.post("/auth/token", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_jobs_endpoints_503_when_queue_unavailable():
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
    session.add(User(email="viewer2@example.com", hashed_password=hash_password("viewerpass"), role=UserRole.VIEWER))
    session.commit()
    session.close()

    try:
        with TestClient(app) as test_client:
            # main_module._job_queue is whatever the real (Redis-disabled-by-
            # default) lifespan set it to — None/disabled, exactly the case
            # this test wants.
            token = _token(test_client, "viewer2@example.com", "viewerpass")
            r = test_client.get("/jobs/some-id", headers=_auth(token))
            assert r.status_code == 503
    finally:
        app.dependency_overrides.pop(get_db, None)
        engine.dispose()


def test_sync_async_requires_admin(client):
    test_client, _ = client
    token = _token(test_client, "viewer@example.com", "viewerpass")
    r = test_client.post("/sync/async", headers=_auth(token))
    assert r.status_code == 403


def test_sync_async_enqueues_and_is_pollable(client, monkeypatch):
    test_client, fake_queue = client
    # Avoid actually running a full sync (and its outbound-ish provider
    # setup) inside this request — register a stub handler so the test is
    # about the enqueue/poll contract, not FullSyncService itself (that's
    # covered by test_job_handlers.py).
    fake_queue.register("full_sync", lambda payload: {"ok": True})

    token = _token(test_client, "admin@example.com", "adminpass")
    r = test_client.post("/sync/async", headers=_auth(token))
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "PENDING"
    job_id = body["job_id"]

    fake_queue.process_next(timeout=0.1)

    r2 = test_client.get(f"/jobs/{job_id}", headers=_auth(token))
    assert r2.status_code == 200
    assert r2.json()["status"] == "SUCCEEDED"
    assert r2.json()["result"] == {"ok": True}

    audit = test_client.get("/audit-logs", headers=_auth(token)).json()
    assert any(row["action"] == "TRIGGER_FULL_SYNC_ASYNC" for row in audit)


def test_simulate_async_enqueues_and_is_pollable(client):
    test_client, fake_queue = client
    fake_queue.register("season_simulation", lambda payload: {"scenario_id": "abc123"})

    token = _token(test_client, "viewer@example.com", "viewerpass")
    r = test_client.post("/simulations/async", headers=_auth(token), params={"competition": "prov:X"})
    assert r.status_code == 202
    job_id = r.json()["job_id"]

    fake_queue.process_next(timeout=0.1)

    r2 = test_client.get(f"/jobs/{job_id}", headers=_auth(token))
    assert r2.json()["status"] == "SUCCEEDED"
    assert r2.json()["result"] == {"scenario_id": "abc123"}


def test_get_unknown_job_is_404(client):
    test_client, _ = client
    token = _token(test_client, "viewer@example.com", "viewerpass")
    r = test_client.get("/jobs/does-not-exist", headers=_auth(token))
    assert r.status_code == 404


def test_dead_letter_endpoint_is_admin_only(client):
    test_client, _ = client
    token = _token(test_client, "viewer@example.com", "viewerpass")
    r = test_client.get("/jobs/dead-letter", headers=_auth(token))
    assert r.status_code == 403


def test_dead_letter_endpoint_lists_failed_jobs(client):
    test_client, fake_queue = client

    def _always_fails(payload):
        raise ValueError("boom")

    fake_queue.register("full_sync", _always_fails)
    fake_queue.settings.job_max_retries = 0

    token = _token(test_client, "admin@example.com", "adminpass")
    r = test_client.post("/sync/async", headers=_auth(token))
    job_id = r.json()["job_id"]

    fake_queue.process_next(timeout=0.1)

    r2 = test_client.get("/jobs/dead-letter", headers=_auth(token))
    assert r2.status_code == 200
    assert any(row["job_id"] == job_id for row in r2.json())
