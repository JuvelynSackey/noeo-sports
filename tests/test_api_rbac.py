"""API-level authentication/RBAC tests (section 54). Uses a shared
StaticPool in-memory SQLite engine — a plain `sqlite:///:memory:` engine
hands out a fresh, empty database per connection, and FastAPI's TestClient
can dispatch requests from a different thread than the one that seeded the
data, so without StaticPool, later requests would see an empty DB."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.database.models  # noqa: F401 registers all tables
from app.api.main import app
from app.database.base import Base, get_db
from app.database.models.audit import AuditLog, User
from app.database.models.enums import UserRole
from app.services.auth import hash_password


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
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
        User(
            email="disabled@example.com",
            hashed_password=hash_password("whatever"),
            role=UserRole.VIEWER,
            is_active=False,
        )
    )
    session.commit()
    session.close()

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _token(client: TestClient, email: str, password: str) -> str:
    r = client.post("/auth/token", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_login_succeeds_and_returns_role(client):
    r = client.post("/auth/token", data={"username": "admin@example.com", "password": "adminpass"})
    assert r.status_code == 200
    body = r.json()
    assert body["token_type"] == "bearer"
    assert body["role"] == "ADMIN"
    assert body["access_token"]


def test_login_fails_with_same_error_for_unknown_email_and_wrong_password(client):
    r1 = client.post("/auth/token", data={"username": "nobody@example.com", "password": "x"})
    r2 = client.post("/auth/token", data={"username": "admin@example.com", "password": "wrong"})
    assert r1.status_code == 401
    assert r2.status_code == 401
    assert r1.json()["detail"] == r2.json()["detail"]


def test_login_fails_for_disabled_account(client):
    r = client.post("/auth/token", data={"username": "disabled@example.com", "password": "whatever"})
    assert r.status_code == 401


def test_protected_endpoint_requires_a_token(client):
    r = client.get("/competitions")
    assert r.status_code == 401


def test_system_health_does_not_require_a_token(client):
    r = client.get("/system-health")
    assert r.status_code == 200


def test_viewer_can_read_competitions(client):
    token = _token(client, "viewer@example.com", "viewerpass")
    r = client.get("/competitions", headers=_auth(token))
    assert r.status_code == 200


def test_viewer_is_forbidden_from_monitoring_and_raw_model_params(client):
    token = _token(client, "viewer@example.com", "viewerpass")
    assert client.get("/monitoring", headers=_auth(token)).status_code == 403
    assert client.get("/models/nonexistent-version", headers=_auth(token)).status_code == 403


def test_viewer_is_forbidden_from_sync_and_user_management(client):
    token = _token(client, "viewer@example.com", "viewerpass")
    assert client.post("/sync", headers=_auth(token)).status_code == 403
    assert client.get("/users", headers=_auth(token)).status_code == 403
    assert (
        client.post(
            "/users", headers=_auth(token), json={"email": "new@example.com", "password": "x", "role": "VIEWER"}
        ).status_code
        == 403
    )


def test_admin_can_reach_monitoring(client):
    token = _token(client, "admin@example.com", "adminpass")
    r = client.get("/monitoring", headers=_auth(token))
    assert r.status_code == 200


def test_admin_can_create_user_and_it_is_audit_logged(client):
    token = _token(client, "admin@example.com", "adminpass")
    r = client.post(
        "/users", headers=_auth(token), json={"email": "new@example.com", "password": "secret123", "role": "ANALYST"}
    )
    assert r.status_code == 201
    body = r.json()
    assert body["email"] == "new@example.com"
    assert body["role"] == "ANALYST"

    new_token = _token(client, "new@example.com", "secret123")
    r2 = client.get("/model-performance", headers=_auth(new_token))
    assert r2.status_code == 200

    audit_r = client.get("/audit-logs", headers=_auth(token))
    assert audit_r.status_code == 200
    actions = [row["action"] for row in audit_r.json()]
    assert "CREATE_USER" in actions


def test_admin_can_deactivate_a_user_and_their_existing_token_stops_working(client):
    admin_token = _token(client, "admin@example.com", "adminpass")
    viewer_token = _token(client, "viewer@example.com", "viewerpass")

    r = client.get("/users", headers=_auth(admin_token))
    viewer_id = next(u["id"] for u in r.json() if u["email"] == "viewer@example.com")

    r2 = client.patch(f"/users/{viewer_id}", headers=_auth(admin_token), json={"is_active": False})
    assert r2.status_code == 200
    assert r2.json()["is_active"] is False

    r3 = client.get("/competitions", headers=_auth(viewer_token))
    assert r3.status_code == 401


def test_create_user_rejects_duplicate_email(client):
    token = _token(client, "admin@example.com", "adminpass")
    r = client.post(
        "/users", headers=_auth(token), json={"email": "viewer@example.com", "password": "x", "role": "VIEWER"}
    )
    assert r.status_code == 409
