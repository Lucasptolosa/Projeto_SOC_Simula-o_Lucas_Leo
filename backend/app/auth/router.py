from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, SecretStr
from sqlalchemy.orm import Session

from app.auth.dependencies import get_auth_settings, get_current_user, require_origin
from app.auth.service import COOKIE_NAME, InvalidCredentials, authenticate, csrf_token, issue_session, revoke_session, utc_now
from app.core.config import Settings
from app.db.session import get_session
from app.users.models import User


router = APIRouter(prefix="/auth", tags=["Autenticação"])


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    username: str
    password: SecretStr


def public_user(user: User, token: str) -> dict:
    return {
        "id": str(user.id), "username": user.username,
        "role": user.role.value, "status": user.status.value,
        "csrf_token": csrf_token(token),
    }


@router.post("/login", dependencies=[Depends(require_origin)])
def login(
    payload: LoginInput, request: Request, response: Response,
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_auth_settings)],
):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(status_code=415, detail="Envie application/json.")
    try:
        user = authenticate(db, payload.username, payload.password.get_secret_value())
    except InvalidCredentials:
        raise HTTPException(status_code=401, detail="Credenciais inválidas.") from None
    token = issue_session(db, user, settings.auth_session_seconds, request.cookies.get(COOKIE_NAME))
    body = public_user(user, token)
    db.commit()
    response.set_cookie(
        COOKIE_NAME, token, max_age=settings.auth_session_seconds,
        httponly=True, secure=settings.auth_cookie_secure, samesite="strict", path="/",
    )
    return body


@router.get("/me")
def me(request: Request, user: Annotated[User, Depends(get_current_user)]):
    return public_user(user, request.cookies[COOKIE_NAME])


@router.post("/logout", status_code=204)
def logout(
    request: Request, user: Annotated[User, Depends(get_current_user)],
    db: Annotated[Session, Depends(get_session)],
    settings: Annotated[Settings, Depends(get_auth_settings)],
):
    revoke_session(db, request.cookies.get(COOKIE_NAME), utc_now())
    db.commit()
    response = Response(status_code=204)
    response.delete_cookie(
        COOKIE_NAME, path="/", httponly=True,
        secure=settings.auth_cookie_secure, samesite="strict",
    )
    return response
