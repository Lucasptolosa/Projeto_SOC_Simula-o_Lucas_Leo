import secrets
import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import inspect, select, text, update
from sqlalchemy.exc import IntegrityError

from app.auth import service
from app.auth.dependencies import get_auth_settings
from app.auth.models import AuthSession
from app.auth.service import COOKIE_NAME, token_digest
from app.core.config import Settings
from app.core.passwords import hash_password, verify_password
from app.db.session import get_session
from app.main import app
from app.users.models import User, UserRole, UserStatus


ORIGIN = "https://testserver"


@pytest.fixture
def auth_context(users_db, test_db_settings):
    factory, connection = users_db
    password = secrets.token_urlsafe(24)
    with factory.begin() as db:
        user = User(username="analista", role="ANALYST", password_hash=hash_password(password))
        db.add(user)
        db.flush()
        user_id = user.id
    settings = test_db_settings.model_copy(update={
        "auth_origin": ORIGIN, "auth_cookie_secure": True, "auth_session_seconds": 28800,
    })
    previous_overrides = app.dependency_overrides.copy()
    def override_db():
        with factory() as db:
            yield db
    app.dependency_overrides[get_session] = override_db
    app.dependency_overrides[get_auth_settings] = lambda: settings
    try:
        with TestClient(app, base_url=ORIGIN) as client:
            client.headers["Origin"] = ORIGIN
            yield client, factory, user_id, password, settings
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous_overrides)


def login(client, password, username="analista"):
    return client.post("/auth/login", json={"username": username, "password": password})


@pytest.mark.parametrize("role", list(UserRole))
def test_login_me_cookie_e_sigilo(auth_context, role):
    # Arrange
    client, factory, user_id, password, _ = auth_context
    with factory.begin() as db:
        db.get(User, user_id).role = role

    # Act
    response = login(client, password)
    me = client.get("/auth/me")
    raw_token = client.cookies.get(COOKIE_NAME)
    with factory() as db:
        stored = db.scalar(select(AuthSession))
        password_hash = db.get(User, user_id).password_hash

    # Assert
    assert response.status_code == me.status_code == 200
    assert response.json() == me.json()
    assert me.json()["role"] == role.value
    assert me.json()["id"] == str(user_id)
    assert len(raw_token) == 43
    assert stored.token_hash == token_digest(raw_token)
    assert stored.token_hash != raw_token
    assert stored.expires_at - stored.created_at == timedelta(hours=8)
    assert "token" not in inspect(AuthSession).columns
    for secret in [password, password_hash, raw_token, stored.token_hash]:
        assert secret not in response.text + me.text
    cookie = response.headers["set-cookie"].lower()
    assert "httponly" in cookie and "secure" in cookie and "samesite=strict" in cookie
    assert "path=/" in cookie and "domain=" not in cookie
    assert response.headers["cache-control"] == me.headers["cache-control"] == "no-store"


def test_credenciais_invalidas_mesma_resposta(auth_context):
    # Arrange
    client, factory, user_id, password, _ = auth_context

    # Act
    unknown = login(client, password, "inexistente")
    incorrect = login(client, secrets.token_urlsafe(24))
    with factory.begin() as db:
        db.get(User, user_id).status = UserStatus.INACTIVE
    inactive = login(client, password)

    # Assert
    assert unknown.status_code == incorrect.status_code == inactive.status_code == 401
    assert unknown.json() == incorrect.json() == inactive.json() == {"detail": "Credenciais inválidas."}
    assert COOKIE_NAME not in client.cookies
    with factory() as db:
        assert db.scalar(select(AuthSession.id)) is None


@pytest.mark.parametrize("token", [None, "", "incorreto", "!" * 43, "a" * 42, "a" * 44, "a" * 43])
def test_sessao_invalida(auth_context, token):
    # Arrange
    client, _, _, _, _ = auth_context
    if token is not None:
        client.cookies.set(COOKIE_NAME, token)

    # Act
    response = client.get("/auth/me")

    # Assert
    assert response.status_code == 401
    assert response.json() == {"detail": "Autenticação necessária."}
    assert response.headers["cache-control"] == "no-store"


def test_logout_revoga_e_impede_replay(auth_context):
    # Arrange
    client, factory, _, password, _ = auth_context
    authenticated = login(client, password)
    raw_token = client.cookies.get(COOKIE_NAME)

    # Act
    response = client.post("/auth/logout", headers={"X-CSRF-Token": authenticated.json()["csrf_token"]})
    client.cookies.set(COOKIE_NAME, raw_token)
    replay = client.get("/auth/me")

    # Assert
    assert response.status_code == 204 and response.content == b""
    assert "max-age=0" in response.headers["set-cookie"].lower()
    assert replay.status_code == 401
    with factory() as db:
        assert db.scalar(select(AuthSession.revoked_at)) is not None


def test_expiracao_limite_exato(auth_context, monkeypatch):
    # Arrange
    client, _, _, password, settings = auth_context
    start = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(service, "utc_now", lambda: start)
    assert login(client, password).status_code == 200

    # Act
    monkeypatch.setattr(service, "utc_now", lambda: start + timedelta(seconds=settings.auth_session_seconds - 1))
    before = client.get("/auth/me")
    monkeypatch.setattr(service, "utc_now", lambda: start + timedelta(seconds=settings.auth_session_seconds))
    boundary = client.get("/auth/me")

    # Assert
    assert before.status_code == 200
    assert boundary.status_code == 401


def test_revogacao_no_servidor(auth_context):
    # Arrange
    client, factory, _, password, _ = auth_context
    assert login(client, password).status_code == 200

    # Act
    with factory.begin() as db:
        db.execute(update(AuthSession).values(revoked_at=service.utc_now()))
    response = client.get("/auth/me")

    # Assert
    assert response.status_code == 401


def test_inativo_bloqueia_sessao_anterior(auth_context):
    # Arrange
    client, factory, user_id, password, _ = auth_context
    assert login(client, password).status_code == 200

    # Act
    with factory.begin() as db:
        db.get(User, user_id).status = UserStatus.INACTIVE
    response = client.get("/auth/me")

    # Assert
    assert response.status_code == 401


def test_novo_login_rotaciona_sessao(auth_context):
    # Arrange
    client, factory, _, password, _ = auth_context
    first = login(client, password)
    previous_token = client.cookies.get(COOKIE_NAME)

    # Act
    second = login(client, password)
    current_token = client.cookies.get(COOKIE_NAME)
    client.cookies.clear()
    client.cookies.set(COOKIE_NAME, previous_token)
    old_session = client.get("/auth/me")

    # Assert
    assert first.status_code == second.status_code == 200
    assert previous_token != current_token
    assert first.json()["csrf_token"] != second.json()["csrf_token"]
    assert old_session.status_code == 401
    with factory() as db:
        assert len(db.scalars(select(AuthSession)).all()) == 2


@pytest.mark.parametrize("origin", [None, "null", "https://evil.test", "https://testserver.evil.test"])
def test_login_csrf_origem(auth_context, origin):
    # Arrange
    client, factory, _, password, _ = auth_context
    client.headers.pop("origin", None)
    if origin is not None:
        client.headers["Origin"] = origin

    # Act
    response = login(client, password)

    # Assert
    assert response.status_code == 403
    with factory() as db:
        assert db.scalar(select(AuthSession.id)) is None


@pytest.mark.parametrize("mode", ["sem_token", "token_errado", "outra_sessao", "sem_origem", "origem_errada"])
def test_logout_csrf_nao_revoga(auth_context, mode):
    # Arrange
    client, factory, _, password, _ = auth_context
    authenticated = login(client, password)
    csrf = authenticated.json()["csrf_token"]
    if mode == "outra_sessao":
        csrf = service.csrf_token(secrets.token_urlsafe(32))
    if mode == "token_errado":
        csrf = "x" * 64
    headers = {} if mode == "sem_token" else {"X-CSRF-Token": csrf}
    if mode == "sem_origem":
        client.headers.pop("origin")
    if mode == "origem_errada":
        client.headers["Origin"] = "https://evil.test"

    # Act
    response = client.post("/auth/logout", headers=headers)
    still_active = client.get("/auth/me")

    # Assert
    assert response.status_code == 403
    assert still_active.status_code == 200
    with factory() as db:
        assert db.scalar(select(AuthSession.revoked_at)) is None


def test_login_recusa_formulario(auth_context):
    # Arrange
    client, _, _, password, _ = auth_context

    # Act
    response = client.post("/auth/login", data={"username": "analista", "password": password})

    # Assert
    assert response.status_code in {415, 422}
    assert password not in response.text


@pytest.mark.parametrize("mode", ["password_objeto", "campo_extra", "json_invalido"])
def test_validacao_sem_segredos(auth_context, mode):
    # Arrange
    client, _, _, password, _ = auth_context
    payload = {"username": "analista", "password": {"secret": password}}
    if mode == "campo_extra":
        payload = {"username": "analista", "password": password, "secret": password}

    # Act
    if mode == "json_invalido":
        response = client.post("/auth/login", content=password, headers={"Content-Type": "application/json"})
    else:
        response = client.post("/auth/login", json=payload)

    # Assert
    assert response.status_code == 422
    assert response.json() == {"detail": "Requisição inválida."}
    assert password not in response.text


def test_falha_servidor_logs_sem_segredos(auth_context, monkeypatch, caplog):
    # Arrange
    from app.auth import router
    client, _, _, password, _ = auth_context
    secret_hash = hash_password(password)
    secret_token = secrets.token_urlsafe(32)
    def fail(*args):
        raise RuntimeError(password + secret_hash + secret_token)
    monkeypatch.setattr(router, "authenticate", fail)
    caplog.set_level("ERROR", logger="mini_soc.server")

    # Act
    response = login(client, password)

    # Assert
    assert response.status_code == 500
    assert response.json() == {"detail": "Falha interna do servidor."}
    assert "timestamp=" in caplog.text
    assert "operation=/auth/login" in caplog.text
    assert "category=RuntimeError" in caplog.text
    for secret in [password, secret_hash, secret_token]:
        assert secret not in response.text + caplog.text


@pytest.mark.parametrize("field,value", [
    ("auth_session_seconds", 0), ("auth_session_seconds", 86401),
    ("auth_origin", "https://app.test/path"),
    ("auth_origin", "https://user:secret@app.test"),
    ("auth_origin", "null"), ("auth_origin", "http://app.test"),
    ("auth_origin", "https://app.test:0"), ("auth_origin", "https://app.test:invalid"),
    ("auth_cookie_secure", False),
])
def test_configuracao_auth_insegura(test_db_settings, field, value):
    # Arrange
    values = test_db_settings.model_dump()
    values.update(auth_origin="https://app.test", auth_cookie_secure=True)
    values[field] = value

    # Act
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)

    # Assert
    assert COOKIE_NAME == "mini_soc_session"


@pytest.mark.parametrize("seconds", [1, 86400])
def test_configuracao_limites_e_http_local(test_db_settings, seconds):
    # Arrange
    values = test_db_settings.model_dump()
    values.update(auth_origin="http://127.0.0.1:8000/", auth_cookie_secure=False, auth_session_seconds=seconds)

    # Act
    settings = Settings(_env_file=None, **values)

    # Assert
    assert settings.auth_origin == "http://127.0.0.1:8000"
    assert settings.auth_session_seconds == seconds


def test_verificacao_argon2_negativa():
    # Arrange
    password = secrets.token_urlsafe(24)
    encoded = hash_password(password)

    # Act
    wrong_password = verify_password(secrets.token_urlsafe(24), encoded)
    wrong_hash = verify_password(password, "hash-invalido")

    # Assert
    assert not wrong_password and not wrong_hash


@pytest.mark.parametrize("kind", ["hash", "expiracao", "usuario"])
def test_integridade_sessao_banco(auth_context, kind):
    # Arrange
    _, factory, user_id, _, _ = auth_context
    now = service.utc_now()
    values = dict(id=uuid4(), user_id=user_id, token_hash="a" * 64, created_at=now, expires_at=now + timedelta(seconds=1))
    if kind == "hash":
        values["token_hash"] = "token-sem-hash"
    if kind == "expiracao":
        values["expires_at"] = now
    if kind == "usuario":
        values["user_id"] = uuid4()

    # Act
    with pytest.raises(IntegrityError):
        with factory.begin() as db:
            db.execute(text(
                "INSERT INTO auth_sessions (id, user_id, token_hash, created_at, expires_at) "
                "VALUES (:id, :user_id, :token_hash, :created_at, :expires_at)"
            ), values)

    # Assert
    with factory() as db:
        assert db.scalar(select(AuthSession.id)) is None


def test_falha_rotacao_preserva_sessao_anterior(auth_context, monkeypatch):
    # Arrange
    from app.auth import router
    client, factory, _, password, _ = auth_context
    assert login(client, password).status_code == 200
    old_token = client.cookies.get(COOKIE_NAME)
    original = router.issue_session
    def fail_after_flush(*args):
        original(*args)
        raise RuntimeError("Falha simulada")
    monkeypatch.setattr(router, "issue_session", fail_after_flush)

    # Act
    failed_login = login(client, password)
    still_active = client.get("/auth/me")

    # Assert
    assert failed_login.status_code == 500
    assert "set-cookie" not in failed_login.headers
    assert client.cookies.get(COOKIE_NAME) == old_token
    assert still_active.status_code == 200
    with factory() as db:
        sessions = db.scalars(select(AuthSession)).all()
        assert len(sessions) == 1
        assert sessions[0].revoked_at is None


def test_http_local_cookie_funcional(auth_context):
    # Arrange
    _, _, _, password, settings = auth_context
    values = settings.model_dump()
    values.update(auth_origin="http://127.0.0.1:8000", auth_cookie_secure=False)
    local_settings = Settings(_env_file=None, **values)
    app.dependency_overrides[get_auth_settings] = lambda: local_settings

    # Act
    with TestClient(app, base_url=local_settings.auth_origin) as client:
        client.headers["Origin"] = local_settings.auth_origin
        response = login(client, password)
        me = client.get("/auth/me")

    # Assert
    assert response.status_code == me.status_code == 200
    cookie = response.headers["set-cookie"].lower()
    assert "secure" not in cookie
    assert "httponly" in cookie and "samesite=strict" in cookie


def test_login_exige_content_type(auth_context):
    # Arrange
    client, _, _, password, _ = auth_context
    content = json.dumps({"username": "analista", "password": password})

    # Act
    response = client.post("/auth/login", content=content)

    # Assert
    assert response.status_code in {415, 422}
    assert password not in response.text
