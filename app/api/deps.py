"""Authentication/authorization dependencies (MASTER BUILD PROMPT section
54). A bearer JWT (issued by `POST /auth/token`) identifies the caller;
`require_roles` gates the administrator-only surface — raw model
parameters, drift monitoring, full-sync triggers, user management, audit
logs — while `get_current_user` alone is enough for the read-only
forecast/competition endpoints any authenticated role can use."""
from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database.base import get_db
from app.database.models.audit import User
from app.database.models.enums import UserRole
from app.services.auth import InvalidTokenError, decode_access_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

_CREDENTIALS_ERROR = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Could not validate credentials",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> User:
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
