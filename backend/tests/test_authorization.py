import secrets
from datetime import timedelta
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.auth.authorization import require_roles
from app.auth.dependencies import get_auth_settings
from app.auth.models import AuthSession
from app.auth.router import router as auth_router
from app.auth.service import COOKIE_NAME, utc_now
from app.core.passwords import hash_password
from app.db.session import get_session
from app.main import app as production_app
from app.users.models import User, UserRole, UserStatus


ORIGIN = "https://testserver"


@pytest.fixture
def rbac_context(users_db, test_db_settings):
    factory, _ = users_db
    password = secrets.token_urlsafe(24)
    with factory.begin() as db:
        user = User(username="operador", role="ANALYST", password_hash=hash_password(password))
        db.add(user)
        db.flush()
        user_id = user.id

    isolated_app = FastAPI()
    isolated_app.include_router(auth_router)
    calls = []
    def register_probe(path, roles):
        checker = require_roles(*roles)
        def probe(user: Annotated[User, Depends(checker)]):
            calls.append(path)
            return {"id": str(user.id), "role": user.role.value}
        for method in ("GET", "POST"):
            isolated_app.add_api_route(path, probe, methods=[method])
    register_probe("/probe/admin", [UserRole.ADMIN])
    register_probe("/probe/analyst", [UserRole.ANALYST])
    register_probe("/probe/shared", [UserRole.ADMIN, UserRole.ANALYST])

    settings = test_db_settings.model_copy(update={
        "auth_origin": ORIGIN, "auth_cookie_secure": True,
    })
    def override_db():
        with factory() as db:
            yield db
    isolated_app.dependency_overrides[get_session] = override_db
    isolated_app.dependency_overrides[get_auth_settings] = lambda: settings
    with TestClient(isolated_app, base_url=ORIGIN) as client:
        client.headers["Origin"] = ORIGIN
        yield client, factory, user_id, password, calls


def login(client, password):
    response = client.post("/auth/login", json={"username": "operador", "password": password})
    assert response.status_code == 200
    return response.json()["csrf_token"]


@pytest.mark.parametrize("role,path,expected", [
    (UserRole.ADMIN, "/probe/admin", 200),
    (UserRole.ANALYST, "/probe/analyst", 200),
    (UserRole.ADMIN, "/probe/analyst", 403),
    (UserRole.ANALYST, "/probe/admin", 403),
    (UserRole.ADMIN, "/probe/shared", 200),
    (UserRole.ANALYST, "/probe/shared", 200),
])
def test_papeis_explicitos(rbac_context, role, path, expected):
    # Arrange
    client, factory, user_id, password, calls = rbac_context
    with factory.begin() as db:
        db.get(User, user_id).role = role
    login(client, password)

    # Act
    response = client.get(path)

    # Assert
    assert response.status_code == expected
    assert len(calls) == (1 if expected == 200 else 0)
    if expected == 200:
        assert response.json() == {"id": str(user_id), "role": role.value}
    else:
        assert response.json() == {"detail": "Permissão insuficiente."}
    assert password not in response.text


@pytest.mark.parametrize("case", ["ausente", "invalida", "expirada", "revogada", "inativo"])
def test_preserva_autenticacao(rbac_context, case):
    # Arrange
    client, factory, user_id, password, calls = rbac_context
    if case == "invalida":
        client.cookies.set(COOKIE_NAME, "token-invalido")
    elif case != "ausente":
        login(client, password)
        with factory.begin() as db:
            session = db.scalar(select(AuthSession))
            if case == "expirada":
                now = utc_now()
                session.created_at = now - timedelta(seconds=2)
                session.expires_at = now - timedelta(seconds=1)
            elif case == "revogada":
                session.revoked_at = utc_now()
            elif case == "inativo":
                db.get(User, user_id).status = UserStatus.INACTIVE

    # Act
    response = client.get("/probe/shared", params={"status": "ACTIVE", "role": "ADMIN"})

    # Assert
    assert response.status_code == 401
    assert response.json() == {"detail": "Autenticação necessária."}
    assert calls == []


def test_mudanca_de_papel_sem_novo_login(rbac_context):
    # Arrange
    client, factory, user_id, password, calls = rbac_context
    login(client, password)
    token = client.cookies.get(COOKIE_NAME)
    assert client.get("/probe/admin").status_code == 403

    # Act
    with factory.begin() as db:
        db.get(User, user_id).role = UserRole.ADMIN
    admin_access = client.get("/probe/admin")
    analyst_access = client.get("/probe/analyst")
    with factory.begin() as db:
        db.get(User, user_id).role = UserRole.ANALYST
    removed_access = client.get("/probe/admin")

    # Assert
    assert admin_access.status_code == 200
    assert analyst_access.status_code == removed_access.status_code == 403
    assert client.cookies.get(COOKIE_NAME) == token
    assert calls == ["/probe/admin"]


def test_cliente_nao_escolhe_papel(rbac_context):
    # Arrange
    client, _, user_id, password, calls = rbac_context
    csrf = login(client, password)
    client.cookies.set("role", "ADMIN")
    client.cookies.set("is_admin", "true")

    # Act
    response = client.post(
        "/probe/admin?role=ADMIN&is_admin=true",
        headers={"X-CSRF-Token": csrf, "X-Role": "ADMIN", "X-User-Role": "ADMIN"},
        json={"role": "ADMIN", "is_admin": True, "user_id": str(user_id)},
    )

    # Assert
    assert response.status_code == 403
    assert response.json() == {"detail": "Permissão insuficiente."}
    assert calls == []


@pytest.mark.parametrize("case", ["valido", "sem_csrf", "csrf_errado", "sem_origin", "origin_errado"])
def test_escrita_preserva_csrf(rbac_context, case):
    # Arrange
    client, _, _, password, calls = rbac_context
    csrf = login(client, password)
    headers = {"X-CSRF-Token": csrf}
    if case == "sem_csrf":
        headers = {}
    elif case == "csrf_errado":
        headers["X-CSRF-Token"] = "x" * 64
    elif case == "sem_origin":
        client.headers.pop("origin")
    elif case == "origin_errado":
        client.headers["Origin"] = "https://evil.test"

    # Act
    response = client.post("/probe/analyst", headers=headers)

    # Assert
    expected = 200 if case == "valido" else 403
    assert response.status_code == expected
    assert len(calls) == (1 if case == "valido" else 0)


@pytest.mark.parametrize("roles", [(), ("ADMIN",), ("ROOT",), (None,), (UserRole.ADMIN, "*")])
def test_configuracao_invalida_rejeitada(roles):
    # Arrange
    invalid_roles = roles

    # Act
    with pytest.raises(ValueError) as error:
        require_roles(*invalid_roles)

    # Assert
    assert str(error.value) == "Informe pelo menos um UserRole válido."


def test_rotas_isoladas_de_producao(rbac_context):
    # Arrange
    client, _, _, _, _ = rbac_context

    # Act
    test_paths = set(client.app.openapi()["paths"])
    production_paths = set(production_app.openapi()["paths"])

    # Assert
    assert {"/probe/admin", "/probe/analyst", "/probe/shared"} <= test_paths
    assert not any(path.startswith("/probe/") for path in production_paths)
