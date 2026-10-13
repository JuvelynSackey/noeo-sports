"""API key issuance/verification tests (section 24's "API Management").
Uses the same StaticPool in-memory SQLite pattern as test_api_rbac.py."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.api.deps as deps_module
import app.database.models  # noqa: F401 registers all tables
from app.api.main import app
from app.database.base import Base, get_db
from app.database.models.audit import User
from app.database.models.enums import UserRole
from app.services.auth import hash_password
from app.services.rate_limiter import RateLimiter


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
    session.add(User(email="analyst@example.com", hashed_password=hash_password("analystpass"), role=UserRole.ANALYST))
    session.commit()
    session.close()

    with TestClient(app) as test_client:
        test_client.session_factory = session_factory
        yield test_client

    app.dependency_overrides.pop(get_db, None)
    engine.dispose()


def _token(client: TestClient, email: str, password: str) -> str:
    r = client.post("/auth/token", data={"username": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _api_key(token: str) -> dict:
    return {"X-API-Key": token}


def _create_key(client: TestClient, jwt: str, name: str = "test key") -> dict:
    r = client.post("/api-keys", headers=_auth(jwt), json={"name": name})
    assert r.status_code == 201, r.text
    return r.json()


def test_any_role_can_create_their_own_api_key(client):
    token = _token(client, "viewer@example.com", "viewerpass")
    body = _create_key(client, token, name="my integration")
    assert body["name"] == "my integration"
    assert body["owner_email"] == "viewer@example.com"
    assert body["role"] == "VIEWER"
    assert body["is_active"] is True
    assert body["request_count"] == 0
    assert body["last_used_at"] is None
    assert "." in body["api_key"]  # key_id.secret


def test_api_key_authenticates_like_the_owning_users_jwt(client):
    jwt = _token(client, "viewer@example.com", "viewerpass")
    key = _create_key(client, jwt)["api_key"]

    r = client.get("/competitions", headers=_api_key(key))
    assert r.status_code == 200

    # the key's owner is a VIEWER, so ADMIN/ANALYST-only endpoints are still forbidden
    r2 = client.get("/monitoring", headers=_api_key(key))
    assert r2.status_code == 403


def test_admin_api_key_can_reach_admin_only_endpoints(client):
    jwt = _token(client, "admin@example.com", "adminpass")
    key = _create_key(client, jwt)["api_key"]

    r = client.get("/users", headers=_api_key(key))
    assert r.status_code == 200


def test_malformed_or_wrong_api_key_is_rejected(client):
    assert client.get("/competitions", headers=_api_key("not-a-real-key")).status_code == 401
    assert client.get("/competitions", headers=_api_key("deadbeefdeadbeef.wrongsecret")).status_code == 401


def test_revoked_api_key_is_rejected(client):
    jwt = _token(client, "viewer@example.com", "viewerpass")
    created = _create_key(client, jwt)
    key, key_id = created["api_key"], created["key_id"]

    assert client.get("/competitions", headers=_api_key(key)).status_code == 200

    r = client.patch(f"/api-keys/{key_id}", headers=_auth(jwt), json={"is_active": False})
    assert r.status_code == 200
    assert r.json()["is_active"] is False

    assert client.get("/competitions", headers=_api_key(key)).status_code == 401


def test_deactivating_owning_user_also_blocks_their_api_key(client):
    jwt = _token(client, "viewer@example.com", "viewerpass")
    key = _create_key(client, jwt)["api_key"]
    assert client.get("/competitions", headers=_api_key(key)).status_code == 200

    admin_jwt = _token(client, "admin@example.com", "adminpass")
    session = client.session_factory()
    user = session.query(User).filter_by(email="viewer@example.com").first()
    user.is_active = False
    session.commit()
    session.close()

    assert client.get("/competitions", headers=_api_key(key)).status_code == 401
    assert admin_jwt  # the admin's own session is unaffected; kept for clarity, not asserted further


def test_list_api_keys_scoped_to_owner_except_for_admin(client):
    viewer_jwt = _token(client, "viewer@example.com", "viewerpass")
    analyst_jwt = _token(client, "analyst@example.com", "analystpass")
    admin_jwt = _token(client, "admin@example.com", "adminpass")
    _create_key(client, viewer_jwt, name="viewer key")
    _create_key(client, analyst_jwt, name="analyst key")

    viewer_list = client.get("/api-keys", headers=_auth(viewer_jwt)).json()
    assert len(viewer_list) == 1
    assert viewer_list[0]["owner_email"] == "viewer@example.com"

    admin_list = client.get("/api-keys", headers=_auth(admin_jwt)).json()
    assert len(admin_list) == 2


def test_update_api_key_requires_ownership_or_admin(client):
    viewer_jwt = _token(client, "viewer@example.com", "viewerpass")
    analyst_jwt = _token(client, "analyst@example.com", "analystpass")
    admin_jwt = _token(client, "admin@example.com", "adminpass")
    key_id = _create_key(client, viewer_jwt)["key_id"]

    forbidden = client.patch(f"/api-keys/{key_id}", headers=_auth(analyst_jwt), json={"name": "hijacked"})
    assert forbidden.status_code == 403

    owner_rename = client.patch(f"/api-keys/{key_id}", headers=_auth(viewer_jwt), json={"name": "renamed by owner"})
    assert owner_rename.status_code == 200
    assert owner_rename.json()["name"] == "renamed by owner"

    admin_rename = client.patch(f"/api-keys/{key_id}", headers=_auth(admin_jwt), json={"name": "renamed by admin"})
    assert admin_rename.status_code == 200
    assert admin_rename.json()["name"] == "renamed by admin"


def test_update_unknown_api_key_is_404(client):
    jwt = _token(client, "viewer@example.com", "viewerpass")
    r = client.patch("/api-keys/doesnotexist", headers=_auth(jwt), json={"name": "x"})
    assert r.status_code == 404


def test_api_key_usage_is_tracked(client):
    jwt = _token(client, "viewer@example.com", "viewerpass")
    key = _create_key(client, jwt)["api_key"]

    client.get("/competitions", headers=_api_key(key))
    client.get("/competitions", headers=_api_key(key))

    listing = client.get("/api-keys", headers=_auth(jwt)).json()
    assert listing[0]["request_count"] == 2
    assert listing[0]["last_used_at"] is not None


def test_api_key_requests_are_rate_limited(client):
    jwt = _token(client, "viewer@example.com", "viewerpass")
    key = _create_key(client, jwt)["api_key"]

    original = deps_module._api_key_limiter
    deps_module._api_key_limiter = RateLimiter(max_attempts=2, window_seconds=60)
    try:
        assert client.get("/competitions", headers=_api_key(key)).status_code == 200
        assert client.get("/competitions", headers=_api_key(key)).status_code == 200
        r = client.get("/competitions", headers=_api_key(key))
        assert r.status_code == 429
    finally:
        deps_module._api_key_limiter = original
