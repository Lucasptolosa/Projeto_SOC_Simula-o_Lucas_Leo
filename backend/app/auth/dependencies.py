import hmac
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.auth.service import COOKIE_NAME, csrf_token, session_user
from app.core.config import Settings
from app.db.session import get_session
from app.users.models import User


def get_auth_settings() -> Settings:
    return Settings()


def require_origin(request: Request, settings: Annotated[Settings, Depends(get_auth_settings)]) -> None:
    if request.headers.get("origin") != settings.auth_origin:
        raise HTTPException(status_code=403, detail="Origem não autorizada.")


def get_current_user(
    request: Request,
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_auth_settings)],
) -> User:
    token = request.cookies.get(COOKIE_NAME)
    user = session_user(db, token)
    if user is None:
        raise HTTPException(status_code=401, detail="Autenticação necessária.")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        require_origin(request, settings)
        supplied = request.headers.get("x-csrf-token", "")
        if not hmac.compare_digest(supplied.encode("utf-8"), csrf_token(token).encode("ascii")):
            raise HTTPException(status_code=403, detail="Proteção CSRF inválida.")
    return user
