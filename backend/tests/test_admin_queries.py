import secrets
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, select

from app.audit.models import AuditLog
from app.auth.dependencies import get_auth_settings
from app.auth.service import COOKIE_NAME
from app.core.passwords import hash_password
from app.db.session import get_session
from app.main import app
from app.users.models import User, UserRole, UserStatus


ORIGIN = "https://testserver"


def authenticated(client, username, password):
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]


@pytest.fixture
def queries(users_db, test_db_settings):
    factory, connection = users_db
    password = secrets.token_urlsafe(24)
    encoded = hash_password(password)
    data = [
        (3, "charlie", "ANALYST", "INACTIVE"), (1, "alpha", "ADMIN", "ACTIVE"),
        (5, "echo", "ANALYST", "ACTIVE"), (2, "bravo", "ANALYST", "ACTIVE"),
        (4, "delta", "ADMIN", "INACTIVE"),
    ]
    with factory.begin() as db:
        db.add_all([User(
            id=UUID(int=number), username=name, role=role, status=status, password_hash=encoded,
        ) for number, name, role, status in data])
    settings = test_db_settings.model_copy(update={"auth_origin": ORIGIN, "auth_cookie_secure": True})
    previous = app.dependency_overrides.copy()
    def database():
        with factory() as db:
            yield db
    app.dependency_overrides[get_session] = database
    app.dependency_overrides[get_auth_settings] = lambda: settings
    try:
        with TestClient(app, base_url=ORIGIN) as client:
            client.headers["Origin"] = ORIGIN
            authenticated(client, "alpha", password)
            yield client, factory, connection, password, encoded
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def seed_audits(factory):
    start = datetime(2026, 10, 30, 10, tzinfo=timezone.utc)
    with factory.begin() as db:
        for number, hours in [(101, 1), (100, 0), (103, 2), (102, 1)]:
            db.add(AuditLog(
                id=UUID(int=number), author_id=UUID(int=1), action="USER_UPDATED",
                entity_type="USER", entity_id=str(UUID(int=2)), occurred_at=start + timedelta(hours=hours),
                old_role=UserRole.ANALYST if number == 102 else None,
                new_role=UserRole.ADMIN if number == 102 else None,
            ))


def audit_snapshot(factory):
    with factory() as db:
        return [tuple(getattr(row, column.name) for column in AuditLog.__table__.columns)
                for row in db.scalars(select(AuditLog).order_by(AuditLog.id)).all()]


def test_admin_consulta_users_publicos(queries, caplog):
    # Arrange
    client, _, _, password, encoded = queries
    token = client.cookies.get(COOKIE_NAME)

    # Act
    response = client.get("/users")

    # Assert
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "total", "page", "page_size"}
    assert body["total"] == 5 and body["page"] == 1 and body["page_size"] == 20
    assert [row["username"] for row in body["items"]] == ["alpha", "bravo", "charlie", "delta", "echo"]
    assert all(set(row) == {"id", "username", "role", "status"} for row in body["items"])
    assert {row["status"] for row in body["items"]} == {"ACTIVE", "INACTIVE"}
    assert response.headers["cache-control"] == "no-store"
    for secret in [password, encoded, token]:
        assert secret not in response.text + caplog.text


@pytest.mark.parametrize("path", ["/users", "/audit-logs"])
@pytest.mark.parametrize("actor,status", [("anonymous", 401), ("bravo", 403)])
def test_consultas_somente_admin(queries, path, actor, status):
    # Arrange
    client, _, _, password, _ = queries
    if actor == "anonymous":
        client.cookies.clear()
    else:
        authenticated(client, actor, password)

    # Act
    response = client.get(path)

    # Assert
    assert response.status_code == status
    assert "items" not in response.json()
    assert response.headers["cache-control"] == "no-store"


def test_paginacao_users_deterministica(queries):
    # Arrange
    client, _, _, _, _ = queries

    # Act
    pages = [client.get("/users", params={"page": page, "page_size": 2}).json()
             for page in [1, 2, 3, 4]]
    repeated = client.get("/users", params={"page": 2, "page_size": 2}).json()

    # Assert
    assert [[row["username"] for row in page["items"]] for page in pages] == [
        ["alpha", "bravo"], ["charlie", "delta"], ["echo"], [],
    ]
    assert all(page["total"] == 5 and page["page_size"] == 2 for page in pages)
    assert repeated == pages[1]


@pytest.mark.parametrize("filters,names", [
    ({"role": "ANALYST"}, ["bravo", "charlie", "echo"]),
    ({"status": "INACTIVE"}, ["charlie", "delta"]),
    ({"role": "ANALYST", "status": "INACTIVE"}, ["charlie"]),
    ({"role": "ADMIN", "status": "ACTIVE"}, ["alpha"]),
])
def test_filtros_users_combinados(queries, filters, names):
    # Arrange
    client, _, _, _, _ = queries

    # Act
    response = client.get("/users", params=filters)

    # Assert
    assert response.status_code == 200
    assert [row["username"] for row in response.json()["items"]] == names
    assert response.json()["total"] == len(names)


def test_pagina_aplicada_apos_filtro(queries):
    # Arrange
    client, _, _, _, _ = queries

    # Act
    response = client.get("/users", params={"role": "ANALYST", "page": 2, "page_size": 1})

    # Assert
    assert response.status_code == 200
    assert response.json()["total"] == 3
    assert [row["username"] for row in response.json()["items"]] == ["charlie"]


def test_filtro_sem_resultados(queries):
    # Arrange
    client, factory, _, _, _ = queries
    with factory.begin() as db:
        db.get(User, UUID(int=3)).status = UserStatus.ACTIVE

    # Act
    response = client.get("/users", params={"role": "ANALYST", "status": "INACTIVE"})

    # Assert
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "page": 1, "page_size": 20}


@pytest.mark.parametrize("path", ["/users", "/audit-logs"])
@pytest.mark.parametrize("params", [
    {"page": 0}, {"page": -1}, {"page": 10001}, {"page": "abc"}, {"page": "1.5"},
    {"page_size": 0}, {"page_size": -1}, {"page_size": 101}, {"page_size": "abc"},
    {"extra": "nao-permitido"},
])
def test_paginacao_invalida(queries, path, params):
    # Arrange
    client, _, _, _, _ = queries

    # Act
    response = client.get(path, params=params)

    # Assert
    assert response.status_code == 422
    assert response.json() == {"detail": "Requisição inválida."}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("filters", [{"role": "ROOT"}, {"status": "DELETED"}, {"role": ""}])
def test_filtros_invalidos(queries, filters):
    # Arrange
    client, _, _, _, _ = queries

    # Act
    response = client.get("/users", params=filters)

    # Assert
    assert response.status_code == 422


@pytest.mark.parametrize("path", ["/users", "/audit-logs"])
@pytest.mark.parametrize("size", [1, 100])
def test_limites_validos(queries, path, size):
    # Arrange
    client, _, _, _, _ = queries

    # Act
    response = client.get(path, params={"page": 10000, "page_size": size})

    # Assert
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["page"] == 10000 and response.json()["page_size"] == size


def test_limite_maximo_aplicado_no_banco(queries):
    # Arrange
    client, factory, _, _, encoded = queries
    with factory.begin() as db:
        db.add_all([User(username=f"u{number:03d}", role="ANALYST", password_hash=encoded)
                    for number in range(105)])

    # Act
    first = client.get("/users", params={"page_size": 100}).json()
    second = client.get("/users", params={"page_size": 100, "page": 2}).json()

    # Assert
    assert first["total"] == second["total"] == 110
    assert len(first["items"]) == 100 and len(second["items"]) == 10
    assert not {row["id"] for row in first["items"]} & {row["id"] for row in second["items"]}


def test_auditoria_ordenada_com_desempate_e_dados(queries, caplog):
    # Arrange
    client, factory, _, password, encoded = queries
    seed_audits(factory)

    # Act
    response = client.get("/audit-logs")
    body = response.json()

    # Assert
    assert response.status_code == 200
    assert body["total"] == 4
    assert [row["id"] for row in body["items"]] == [str(UUID(int=n)) for n in [103, 102, 101, 100]]
    for row in body["items"]:
        assert set(row) == {"id", "author_id", "action", "entity_type", "entity_id", "occurred_at", "old_role", "new_role"}
        assert row["author_id"] == str(UUID(int=1)) and row["action"] == "USER_UPDATED"
        assert row["entity_type"] == "USER" and row["entity_id"] == str(UUID(int=2))
        assert datetime.fromisoformat(row["occurred_at"].replace("Z", "+00:00")).tzinfo is not None
    changed = body["items"][1]
    assert changed["old_role"] == "ANALYST" and changed["new_role"] == "ADMIN"
    assert body["items"][0]["old_role"] is body["items"][0]["new_role"] is None
    for secret in [password, encoded, client.cookies.get(COOKIE_NAME)]:
        assert secret not in response.text + caplog.text


def test_paginacao_auditoria_estavel(queries):
    # Arrange
    client, factory, _, _, _ = queries
    seed_audits(factory)

    # Act
    first = client.get("/audit-logs", params={"page_size": 2}).json()
    second = client.get("/audit-logs", params={"page_size": 2, "page": 2}).json()
    again = client.get("/audit-logs", params={"page_size": 2, "page": 2}).json()

    # Assert
    assert [row["id"] for row in first["items"]] == [str(UUID(int=103)), str(UUID(int=102))]
    assert [row["id"] for row in second["items"]] == [str(UUID(int=101)), str(UUID(int=100))]
    assert first["total"] == second["total"] == 4
    assert again == second


def test_auditoria_vazia_nao_cria_eventos(queries):
    # Arrange
    client, factory, _, _, _ = queries
    before = audit_snapshot(factory)

    # Act
    response = client.get("/audit-logs")

    # Assert
    assert response.status_code == 200
    assert response.json() == {"items": [], "total": 0, "page": 1, "page_size": 20}
    assert audit_snapshot(factory) == before == []


def test_consultas_somente_leitura(queries):
    # Arrange
    client, factory, connection, password, _ = queries
    created = client.post("/users", json={"username": "novo", "role": "ANALYST", "password": password})
    assert created.status_code == 201
    before = audit_snapshot(factory)
    statements = []
    def record_statement(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement.strip().upper())
    event.listen(connection, "before_cursor_execute", record_statement)
    client.headers.pop("origin")
    client.headers.pop("x-csrf-token")

    # Act
    try:
        responses = [client.get(path) for path in ["/users", "/audit-logs", "/audit-logs", "/users"]]
    finally:
        event.remove(connection, "before_cursor_execute", record_statement)

    # Assert
    assert all(response.status_code == 200 for response in responses)
    assert statements and not any(sql.startswith(("INSERT", "UPDATE", "DELETE", "CREATE", "DROP", "ALTER")) for sql in statements)
    assert audit_snapshot(factory) == before
    assert len(before) == 1


@pytest.mark.parametrize("actor", ["alpha", "bravo"])
@pytest.mark.parametrize("method", ["POST", "PATCH", "PUT", "DELETE"])
def test_auditoria_permanece_sem_mutacao_por_api(queries, actor, method):
    # Arrange
    client, factory, _, password, _ = queries
    seed_audits(factory)
    before = audit_snapshot(factory)
    if actor != "alpha":
        authenticated(client, actor, password)

    # Act
    response = client.request(method, "/audit-logs", json={"action": "ALTERADA"})

    # Assert
    assert response.status_code == 405
    assert audit_snapshot(factory) == before
