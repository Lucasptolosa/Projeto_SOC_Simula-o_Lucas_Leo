import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.auth.models import AuthSession
from app.core.passwords import hash_password, verify_password
from app.users.models import User, UserStatus


COOKIE_NAME = "mini_soc_session"
_DUMMY_HASH = hash_password(secrets.token_urlsafe(32))


class InvalidCredentials(ValueError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def token_digest(token: str | None) -> str | None:
    if token is None or re.fullmatch(r"[A-Za-z0-9_-]{43}", token) is None:
        return None
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def csrf_token(token: str) -> str:
    return hmac.new(token.encode("ascii"), b"mini-soc:csrf:v1", hashlib.sha256).hexdigest()


def authenticate(db: Session, username: str, password: str) -> User:
    user = db.scalar(select(User).where(User.username == username).with_for_update())
    # Reduz enumeração temporal
    encoded = user.password_hash if user is not None else _DUMMY_HASH
    valid = verify_password(password, encoded)
    if not valid or user is None or user.status is not UserStatus.ACTIVE:
        raise InvalidCredentials
    return user


def revoke_session(db: Session, token: str | None, now: datetime) -> None:
    digest = token_digest(token)
    if digest is not None:
        db.execute(update(AuthSession).where(
            AuthSession.token_hash == digest,
            AuthSession.revoked_at.is_(None),
        ).values(revoked_at=now))


def revoke_user_sessions(db: Session, user_id, now: datetime) -> None:
    db.execute(update(AuthSession).where(
        AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None),
    ).values(revoked_at=now))


def issue_session(db: Session, user: User, seconds: int, previous: str | None) -> str:
    now = utc_now()
    revoke_session(db, previous, now)
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(
        user_id=user.id, token_hash=token_digest(token),
        created_at=now, expires_at=now + timedelta(seconds=seconds),
    ))
    db.flush()
    return token


def session_user(db: Session, token: str | None) -> User | None:
    digest = token_digest(token)
    if digest is None:
        return None
    return db.scalar(select(User).join(AuthSession, AuthSession.user_id == User.id).where(
        AuthSession.token_hash == digest,
        AuthSession.revoked_at.is_(None),
        AuthSession.expires_at > utc_now(),
        User.status == UserStatus.ACTIVE,
    ).execution_options(populate_existing=True))
