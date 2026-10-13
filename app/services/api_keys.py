"""API key issuance and verification (MASTER BUILD PROMPT section 24's
"API Management"). A presented key is `{key_id}.{secret}` — `key_id` is
an indexed, non-secret lookup column (so verification is a single
indexed query plus one bcrypt check, not a scan over every stored hash),
`secret` is checked against its bcrypt hash via the same primitives
`app/services/auth.py` uses for passwords.
"""
from __future__ import annotations

import secrets

from sqlalchemy.orm import Session

from app.database.models.api_keys import ApiKey
from app.services.auth import hash_password, verify_password

_KEY_ID_BYTES = 8
_SECRET_BYTES = 32


def generate_api_key(db: Session, *, user_id: int, name: str) -> tuple[ApiKey, str]:
    """Creates and persists a new key, returning the row and the ONE-TIME
    plaintext key the caller must save now — only its hash is persisted,
    so a lost key can't be recovered, only revoked and replaced."""
    key_id = secrets.token_hex(_KEY_ID_BYTES)
    secret = secrets.token_urlsafe(_SECRET_BYTES)
    api_key = ApiKey(key_id=key_id, hashed_secret=hash_password(secret), name=name, user_id=user_id)
    db.add(api_key)
    db.flush()
    return api_key, f"{key_id}.{secret}"


def verify_api_key(db: Session, presented_key: str) -> ApiKey | None:
    """Returns the matching, still-active `ApiKey` row, or None for any of:
    malformed input, unknown key_id, wrong secret, or a deactivated key —
    callers must not distinguish these to an unauthenticated caller, same
    as `authenticate_user`'s password-login equivalent."""
    key_id, _, secret = presented_key.partition(".")
    if not key_id or not secret:
        return None
    api_key = db.query(ApiKey).filter_by(key_id=key_id).first()
    if api_key is None or not api_key.is_active:
        return None
    if not verify_password(secret, api_key.hashed_secret):
        return None
    return api_key
