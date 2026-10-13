"""Authentication/authorization dependencies (MASTER BUILD PROMPT section
54). Either a bearer JWT (issued by `POST /auth/token`) or an `X-API-Key`
header (issued by `POST /api-keys`, section 24's "API Management")
identifies the caller; `require_roles` gates the administrator-only
surface — raw model parameters, drift monitoring, full-sync triggers,
user management, audit logs — while `get_current_user` alone is enough
for the read-only forecast/competition endpoints any authenticated role
can use. An API key acts with its owning user's own (current, not
snapshotted) role and is rate limited per key, independent of anything
the user's own JWT usage is doing."""
from __future__ import annotations

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.base import get_db
from app.database.models.audit import User
from app.database.models.enums import UserRole
from app.database.models.mixins import utcnow
from app.services.api_keys import verify_api_key
from app.services.auth import InvalidTokenError, decode_access_token
from app.services.rate_limiter import RateLimiter

# auto_error=False: a caller authenticating via X-API-Key instead sends no
# Authorization header at all, and that must not itself be a 401 before
# get_current_user ever gets a chance to check for the API key.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token", auto_error=False)

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)

# A plain module-level singleton, not lifespan-scoped like the login
# limiter in app/api/main.py — rate limiting here is purely a function of
# settings, with no server-lifecycle state to start/stop. Tests that need
# a tight limit swap this out directly and restore it afterward, same
# pattern as main_module._login_limiter.
_api_key_limiter = RateLimiter(
    get_settings().api_key_rate_limit_requests, get_settings().api_key_rate_limit_window_seconds
)


def _authenticate_via_api_key(db: Session, presented_key: str) -> User:
    api_key = verify_api_key(db, presented_key)
    if api_key is None:
        raise _CREDENTIALS_ERROR
    if not _api_key_limiter.check(f"apikey:{api_key.key_id}"):
        raise HTTPException(status_code=429, detail="API key rate limit exceeded")
    user = db.get(User, api_key.user_id)
    if user is None or not user.is_active:
        raise _CREDENTIALS_ERROR
    api_key.last_used_at = utcnow()
    api_key.request_count += 1
    db.commit()
    return user


def get_current_user(
    token: str | None = Depends(oauth2_scheme),
    api_key: str | None = Header(default=None, alias="X-API-Key"),
    db: Session = Depends(get_db),
) -> User:
    if api_key is not None:
        return _authenticate_via_api_key(db, api_key)
    if token is None:
        raise _CREDENTIALS_ERROR
    settings = get_settings()
    try:
        payload = decode_access_token(settings, token)
    except InvalidTokenError:
        raise _CREDENTIALS_ERROR
    email = payload.get("sub")
    if email is None:
        raise _CREDENTIALS_ERROR
    user = db.query(User).filter_by(email=email).first()
    if user is None or not user.is_active:
        raise _CREDENTIALS_ERROR
    return user


def require_roles(*roles: UserRole):
    """A dependency factory rather than a single dependency, since the
    allowed role set differs per endpoint (e.g. ADMIN-only for `/sync` and
    user management vs. ADMIN-or-ANALYST for internal model diagnostics)."""

    def _check(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Insufficient role for this action")
        return user

    return _check
