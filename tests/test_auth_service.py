import datetime as dt

import pytest

from app.config import Settings
from app.database.models.audit import User
from app.database.models.enums import UserRole
from app.services.auth import (
    InvalidTokenError,
    authenticate_user,
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)


def test_hash_password_round_trips():
    hashed = hash_password("correct horse battery staple")
    assert hashed != "correct horse battery staple"
    assert verify_password("correct horse battery staple", hashed)
    assert not verify_password("wrong password", hashed)


def test_create_and_decode_access_token():
    settings = Settings(secret_key="test-secret", access_token_expire_minutes=30)
    user = User(id=1, email="admin@example.com", hashed_password="x", role=UserRole.ADMIN)

    token, expires_at = create_access_token(settings, user=user)
    payload = decode_access_token(settings, token)

    assert payload["sub"] == "admin@example.com"
    assert payload["role"] == "ADMIN"
    assert expires_at > dt.datetime.now(dt.timezone.utc)


def test_decode_access_token_rejects_tampered_or_wrong_key_tokens():
    settings = Settings(secret_key="test-secret")
    other_settings = Settings(secret_key="a-different-secret")
    user = User(id=1, email="a@example.com", hashed_password="x", role=UserRole.VIEWER)

    token, _ = create_access_token(settings, user=user)

    with pytest.raises(InvalidTokenError):
        decode_access_token(other_settings, token)
    with pytest.raises(InvalidTokenError):
        decode_access_token(settings, token + "tampered")


def test_decode_access_token_rejects_expired_token():
    settings = Settings(secret_key="test-secret", access_token_expire_minutes=-1)
    user = User(id=1, email="a@example.com", hashed_password="x", role=UserRole.VIEWER)

    token, _ = create_access_token(settings, user=user)

    with pytest.raises(InvalidTokenError):
        decode_access_token(settings, token)


def test_authenticate_user_rejects_unknown_email(db_session):
    assert authenticate_user(db_session, "nobody@example.com", "whatever") is None


def test_authenticate_user_rejects_wrong_password(db_session):
    db_session.add(User(email="a@example.com", hashed_password=hash_password("correct"), role=UserRole.VIEWER))
    db_session.commit()

    assert authenticate_user(db_session, "a@example.com", "wrong") is None


def test_authenticate_user_rejects_inactive_account(db_session):
    db_session.add(
        User(email="a@example.com", hashed_password=hash_password("correct"), role=UserRole.VIEWER, is_active=False)
    )
    db_session.commit()

    assert authenticate_user(db_session, "a@example.com", "correct") is None


def test_authenticate_user_succeeds_with_correct_credentials(db_session):
    db_session.add(User(email="a@example.com", hashed_password=hash_password("correct"), role=UserRole.VIEWER))
    db_session.commit()

    user = authenticate_user(db_session, "a@example.com", "correct")
    assert user is not None
    assert user.email == "a@example.com"
