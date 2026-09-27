"""Password hashing and JWT issuance/verification (MASTER BUILD PROMPT
section 54) — the primitives `app/api/deps.py` builds the actual
request-time authentication/authorization dependencies on top of."""
from __future__ import annotations

import datetime as dt

from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy.orm import Session

from app.config import Settings
from app.database.models.audit import User

ALGORITHM = "HS256"

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class InvalidTokenError(Exception):
    """Raised for any expired, malformed, or otherwise unusable JWT."""


def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return _pwd_context.verify(plain_password, hashed_password)


def create_access_token(settings: Settings, *, user: User) -> tuple[str, dt.datetime]:
    expires_at = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=settings.access_token_expire_minutes)
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    payload = {"sub": user.email, "role": role, "exp": expires_at}
    token = jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)
    return token, expires_at


def decode_access_token(settings: Settings, token: str) -> dict:
    try:
        return jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except JWTError as exc:
        raise InvalidTokenError(str(exc)) from exc


def authenticate_user(db: Session, email: str, password: str) -> User | None:
    """Returns None (never raises) for any of: unknown email, disabled
    account, wrong password — the caller must not distinguish these to an
    unauthenticated caller, since that would let an attacker enumerate
    valid emails."""
    user = db.query(User).filter_by(email=email).first()
    if user is None or not user.is_active:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
