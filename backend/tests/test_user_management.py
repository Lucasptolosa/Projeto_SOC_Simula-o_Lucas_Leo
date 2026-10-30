import secrets
import time
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from uuid import UUID, uuid4

import pytest
from argon2 import PasswordHasher, extract_parameters
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text, update

from app.audit.models import AuditLog
from app.auth.dependencies import get_auth_settings
from app.auth.models import AuthSession
from app.auth.service import COOKIE_NAME
from app.core.passwords import hash_password
from app.db.session import create_db_engine, create_session_factory, get_session
from app.main import app
from app.users import repository, service
from app.users.models import User, UserRole, UserStatus


ORIGIN = "https://testserver"


def authenticated(client, username, password):
    client.headers["Origin"] = ORIGIN
    response = client.post("/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]


@pytest.fixture
def management(users_db, test_db_settings):
    factory, _ = users_db
    password = secrets.token_urlsafe(24)
    encoded = hash_password(password)
    ids = {}
    with factory.begin() as db:
        for name, role in [("admin-a", "ADMIN"), ("admin-b", "ADMIN"), ("analyst", "ANALYST")]:
            user = User(username=name, role=role, password_hash=encoded)
            db.add(user)
            db.flush()
            ids[name] = user.id
    settings = test_db_settings.model_copy(update={"auth_origin": ORIGIN, "auth_cookie_secure": True})
    previous = app.dependency_overrides.copy()
    def database():
        with factory() as db:
            yield db
    app.dependency_overrides[get_session] = database
    app.dependency_overrides[get_auth_settings] = lambda: settings
    try:
        with TestClient(app, base_url=ORIGIN) as client:
            authenticated(client, "admin-a", password)
            yield client, factory, ids, password
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


@pytest.mark.parametrize("role", list(UserRole))
def test_admin_cadastra_com_auditoria(management, role, caplog):
    # Arrange
    client, factory, ids, _ = management
    password = secrets.token_urlsafe(24)

    # Act
    response = client.post("/users", json={"username": "novo-ç", "role": role.value, "password": password})

    # Assert
    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "ACTIVE" and body["role"] == role.value
    user_id = UUID(body["id"])
    assert response.headers["cache-control"] == "no-store"
    with factory() as db:
        user = db.get(User, user_id)
        assert PasswordHasher().verify(user.password_hash, password)
        assert extract_parameters(user.password_hash).salt_len >= 16
        audits = db.scalars(select(AuditLog)).all()
        assert len(audits) == 1
        audit = audits[0]
        assert audit.author_id == ids["admin-a"]
        assert audit.action == "USER_CREATED" and audit.entity_type == "USER"
        assert audit.entity_id == str(user_id) and audit.occurred_at.tzinfo is not None
        assert audit.old_role is audit.new_role is None
        for secret in [password, user.password_hash]:
            assert secret not in response.text + caplog.text
            assert secret not in str({column.name: getattr(audit, column.name) for column in AuditLog.__table__.columns})
    assert set(body) == {"id", "username", "role", "status"}


@pytest.mark.parametrize("actor,expected", [("anonymous", 401), ("analyst", 403)])
@pytest.mark.parametrize("operation", ["create", "update", "deactivate"])
def test_gerenciamento_somente_admin(management, actor, expected, operation):
    # Arrange
    client, factory, ids, password = management
    if actor == "anonymous":
        client.cookies.clear()
    else:
        authenticated(client, actor, password)

    # Act
    if operation == "create":
        response = client.post("/users", json={"username": "novo", "role": "ADMIN", "password": password})
    elif operation == "update":
        response = client.patch(f"/users/{ids['admin-b']}", json={"role": "ANALYST"})
    else:
        response = client.post(f"/users/{ids['admin-b']}/deactivate")

    # Assert
    assert response.status_code == expected
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 3
        assert db.scalar(select(func.count()).select_from(AuditLog)) == 0


@pytest.mark.parametrize("changes,expected", [
    ({"username": "analyst"}, 409), ({"username": " \t"}, 422),
    ({"role": "ROOT"}, 422), ({"password": ""}, 422),
    ({"password": None}, 422), ({"status": "INACTIVE"}, 422),
    ({"password_hash": "hash-injetado"}, 422), ({"id": str(uuid4())}, 422),
])
def test_cadastro_invalido_sem_segredos(management, changes, expected, caplog):
    # Arrange
    client, factory, _, password = management
    payload = {"username": "novo", "role": "ANALYST", "password": password}
    payload.update(changes)

    # Act
    response = client.post("/users", json=payload)

    # Assert
    assert response.status_code == expected
    assert password not in response.text + caplog.text
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AuditLog)) == 0
        assert db.scalar(select(func.count()).select_from(User)) == 3


@pytest.mark.parametrize("changes", [
    {"username": "renomeado"}, {"role": "ADMIN"}, {"username": "renomeado", "role": "ADMIN"},
])
def test_alteracao_preserva_associacoes_e_audita_uma_vez(management, changes):
    # Arrange
    client, factory, ids, password = management
    with TestClient(app, base_url=ORIGIN) as target_client:
        authenticated(target_client, "analyst", password)
        raw_token = target_client.cookies.get(COOKIE_NAME)

        # Act
        response = client.patch(f"/users/{ids['analyst']}", json=changes)
        repeated = client.patch(f"/users/{ids['analyst']}", json=changes)
        profile = target_client.get("/auth/me")

        # Assert
        assert response.status_code == repeated.status_code == 200
        assert response.json()["id"] == str(ids["analyst"])
        assert profile.json()["username"] == changes.get("username", "analyst")
        assert profile.json()["role"] == changes.get("role", "ANALYST")
        assert target_client.cookies.get(COOKIE_NAME) == raw_token
    with factory() as db:
        assert db.scalar(select(AuthSession.id).where(AuthSession.user_id == ids["analyst"])) is not None
        audits = db.scalars(select(AuditLog)).all()
        assert len(audits) == 1
        assert audits[0].action == "USER_UPDATED"
        assert audits[0].old_role == (UserRole.ANALYST if "role" in changes else None)
        assert audits[0].new_role == (UserRole.ADMIN if "role" in changes else None)


def test_alteracao_de_papel_refletida_no_rbac(management):
    # Arrange
    client, _, ids, password = management
    with TestClient(app, base_url=ORIGIN) as other:
        authenticated(other, "analyst", password)
        payload = {"username": "criado-pelo-promovido", "role": "ANALYST", "password": password}
        assert other.post("/users", json=payload).status_code == 403

        # Act
        changed = client.patch(f"/users/{ids['analyst']}", json={"role": "ADMIN"})
        allowed = other.post("/users", json=payload)

        # Assert
        assert changed.status_code == 200
        assert allowed.status_code == 201


@pytest.mark.parametrize("payload,expected", [
    ({"username": "admin-b"}, 409), ({}, 422), ({"username": None}, 422),
    ({"role": "ROOT"}, 422), ({"status": "INACTIVE"}, 422), ({"password": "nova"}, 422),
])
def test_patch_invalido_preserva_usuario(management, payload, expected):
    # Arrange
    client, factory, ids, _ = management

    # Act
    response = client.patch(f"/users/{ids['analyst']}", json=payload)

    # Assert
    assert response.status_code == expected
    with factory() as db:
        assert db.get(User, ids["analyst"]).username == "analyst"
        assert db.scalar(select(func.count()).select_from(AuditLog)) == 0


def test_proprio_papel_e_username_recusados(management):
    # Arrange
    client, factory, ids, _ = management

    # Act
    role = client.patch(f"/users/{ids['admin-a']}", json={"role": "ANALYST"})
    name = client.patch(f"/users/{ids['admin-a']}", json={"username": "outro"})

    # Assert
    assert role.status_code == name.status_code == 403
    with factory() as db:
        user = db.get(User, ids["admin-a"])
        assert user.role is UserRole.ADMIN and user.username == "admin-a"
        assert db.scalar(select(func.count()).select_from(AuditLog)) == 0


def test_rebaixar_outro_admin_preserva_um_admin(management):
    # Arrange
    client, factory, ids, _ = management

    # Act
    response = client.patch(f"/users/{ids['admin-b']}", json={"role": "ANALYST"})

    # Assert
    assert response.status_code == 200
    with factory() as db:
        assert repository.active_admins(db) == 1
        audit = db.scalar(select(AuditLog))
        assert audit.old_role is UserRole.ADMIN and audit.new_role is UserRole.ANALYST


def test_ultimo_admin_nao_pode_ser_desativado(management):
    # Arrange
    client, factory, ids, password = management
    assert client.post(f"/users/{ids['admin-a']}/deactivate").status_code == 200
    authenticated(client, "admin-b", password)

    # Act
    response = client.post(f"/users/{ids['admin-b']}/deactivate")
    role = client.patch(f"/users/{ids['admin-b']}", json={"role": "ANALYST"})

    # Assert
    assert response.status_code == 409 and role.status_code == 403
    with factory() as db:
        assert repository.active_admins(db) == 1
        assert db.get(User, ids["admin-b"]).status is UserStatus.ACTIVE
        assert db.scalar(select(func.count()).select_from(AuditLog)) == 1


def test_desativacao_revoga_todas_sessoes_definitivamente(management):
    # Arrange
    client, factory, ids, password = management
    with TestClient(app, base_url=ORIGIN) as first, TestClient(app, base_url=ORIGIN) as second:
        authenticated(first, "analyst", password)
        authenticated(second, "analyst", password)

        # Act
        response = client.post(f"/users/{ids['analyst']}/deactivate")
        denied = [first.get("/auth/me"), second.get("/auth/me")]
        new_login = client.post("/auth/login", json={"username": "analyst", "password": password})
        with factory() as db:
            user = db.get(User, ids["analyst"])
            assert user.status is UserStatus.INACTIVE
            sessions = db.scalars(select(AuthSession).where(AuthSession.user_id == user.id)).all()
            assert len(sessions) == 2 and all(row.revoked_at is not None for row in sessions)
        with factory.begin() as db:
            db.get(User, ids["analyst"]).status = UserStatus.ACTIVE
        after_reactivation = [first.get("/auth/me"), second.get("/auth/me")]

        # Assert
        assert response.status_code == 200
        assert all(item.status_code == 401 for item in denied + after_reactivation)
        assert new_login.status_code == 401
        with factory() as db:
            audit = db.scalar(select(AuditLog))
            assert audit.action == "USER_DEACTIVATED" and audit.entity_id == str(ids["analyst"])


def test_repeticao_desativacao_sem_auditoria_duplicada(management):
    # Arrange
    client, factory, ids, _ = management
    assert client.post(f"/users/{ids['analyst']}/deactivate").status_code == 200

    # Act
    response = client.post(f"/users/{ids['analyst']}/deactivate")

    # Assert
    assert response.status_code == 409
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AuditLog)) == 1


@pytest.mark.parametrize("operation", ["create", "update", "deactivate"])
def test_rollback_atomico_da_auditoria(management, monkeypatch, caplog, operation):
    # Arrange
    client, factory, ids, password = management
    with TestClient(app, base_url=ORIGIN) as target:
        authenticated(target, "analyst", password)
        original = service.append_audit
        def fail_after_flush(db, **kwargs):
            original(db, **kwargs)
            db.flush()
            raise RuntimeError(password)
        monkeypatch.setattr(service, "append_audit", fail_after_flush)
        caplog.set_level("ERROR", logger="mini_soc.server")

        # Act
        if operation == "create":
            response = client.post("/users", json={"username": "novo", "role": "ADMIN", "password": password})
        elif operation == "update":
            response = client.patch(f"/users/{ids['analyst']}", json={"role": "ADMIN", "username": "alterado"})
        else:
            response = client.post(f"/users/{ids['analyst']}/deactivate")
        profile = target.get("/auth/me")

        # Assert
        assert response.status_code == 500 and profile.status_code == 200
        assert password not in response.text + caplog.text
        with factory() as db:
            assert db.scalar(select(func.count()).select_from(User)) == 3
            assert db.scalar(select(func.count()).select_from(AuditLog)) == 0
            user = db.get(User, ids["analyst"])
            assert user.username == "analyst" and user.role is UserRole.ANALYST
            assert user.status is UserStatus.ACTIVE
            assert db.scalar(select(AuthSession.revoked_at).where(AuthSession.user_id == user.id)) is None


@pytest.mark.parametrize("method", ["PATCH", "PUT", "DELETE"])
@pytest.mark.parametrize("actor", ["admin-a", "analyst"])
def test_auditoria_sem_interface_de_mutacao(management, method, actor):
    # Arrange
    client, factory, _, password = management
    assert client.post("/users", json={"username": "novo", "role": "ANALYST", "password": password}).status_code == 201
    with factory() as db:
        audit = db.scalar(select(AuditLog))
        audit_id, action = audit.id, audit.action
    authenticated(client, actor, password)

    # Act
    response = client.request(method, f"/audit-logs/{audit_id}", json={"action": "alterada"})

    # Assert
    assert response.status_code in {404, 405}
    with factory() as db:
        assert db.get(AuditLog, audit_id).action == action
        assert db.scalar(select(func.count()).select_from(AuditLog)) == 1


@pytest.mark.parametrize("case", ["sem_csrf", "csrf_errado", "sem_origin", "origin_errado"])
@pytest.mark.parametrize("operation", ["create", "update", "deactivate"])
def test_operacao_administrativa_exige_csrf(management, case, operation):
    # Arrange
    client, factory, ids, password = management
    if case == "sem_csrf":
        client.headers.pop("x-csrf-token")
    elif case == "csrf_errado":
        client.headers["X-CSRF-Token"] = "incorreto"
    elif case == "sem_origin":
        client.headers.pop("origin")
    else:
        client.headers["Origin"] = "https://evil.test"

    # Act
    if operation == "create":
        response = client.post("/users", json={"username": "novo", "role": "ADMIN", "password": password})
    elif operation == "update":
        response = client.patch(f"/users/{ids['admin-b']}", json={"role": "ANALYST"})
    else:
        response = client.post(f"/users/{ids['admin-b']}/deactivate")

    # Assert
    assert response.status_code == 403
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AuditLog)) == 0


@pytest.mark.parametrize("operation", ["patch", "deactivate"])
def test_usuario_inexistente(management, operation):
    # Arrange
    client, _, _, _ = management
    user_id = uuid4()

    # Act
    if operation == "patch":
        response = client.patch(f"/users/{user_id}", json={"username": "outro"})
    else:
        response = client.post(f"/users/{user_id}/deactivate")

    # Assert
    assert response.status_code == 404


@pytest.mark.parametrize("field,value,reason", [
    ("role", UserRole.ANALYST, "forbidden_author"),
    ("status", UserStatus.INACTIVE, "inactive_author"),
])
def test_autor_revalidado_apos_lock(management, field, value, reason):
    # Arrange
    _, factory, ids, password = management

    # Act
    with pytest.raises(service.UserRuleError) as error:
        with factory.begin() as db:
            stale_author = db.get(User, ids["admin-a"])
            db.execute(update(User).where(User.id == stale_author.id).values(
                **{field: value},
            ).execution_options(synchronize_session=False))
            service.create_user(db, stale_author.id, "novo", UserRole.ADMIN, password)

    # Assert
    assert str(error.value) == reason
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AuditLog)) == 0


def test_lock_concorrente_em_duas_transacoes(test_db_connection, test_db_settings):
    # Arrange
    first_factory = create_session_factory(test_db_connection)
    engine = create_db_engine(test_db_settings)
    second_pid = Queue()
    def competitor():
        with create_session_factory(engine)() as db:
            assert db.scalar(text("SELECT current_database()")) == "mini_soc_test"
            second_pid.put(db.scalar(text("SELECT pg_backend_pid()")))
            repository.serialize_user_writes(db)
            db.rollback()
            return True

    try:
        with first_factory() as first, ThreadPoolExecutor(max_workers=1) as pool:
            assert first.scalar(text("SHOW transaction_isolation")) == "read committed"
            repository.serialize_user_writes(first)
            future = pool.submit(competitor)
            pid = second_pid.get(timeout=5)

            # Act
            deadline = time.monotonic() + 3
            blocked = False
            while time.monotonic() < deadline:
                blocked = first.scalar(text(
                    "SELECT EXISTS (SELECT 1 FROM pg_locks "
                    "WHERE pid = :pid AND locktype = 'advisory' AND NOT granted)"
                ), {"pid": pid})
                if blocked:
                    break
                time.sleep(0.01)
            first.rollback()
            released = future.result(timeout=6)

            # Assert
            assert blocked and released
    finally:
        engine.dispose()


def test_colisao_username_tratada_pelo_banco(management, monkeypatch):
    # Arrange
    client, factory, _, password = management
    monkeypatch.setattr(repository, "username_taken", lambda *args: False)

    # Act
    response = client.post("/users", json={"username": "analyst", "role": "ADMIN", "password": password})

    # Assert
    assert response.status_code == 409
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 3
        assert db.scalar(select(func.count()).select_from(AuditLog)) == 0


def test_falha_integridade_auditoria_reverte_cadastro(management, monkeypatch, caplog):
    # Arrange
    client, factory, _, password = management
    original = service.append_audit
    def invalid_author(db, **kwargs):
        kwargs["author_id"] = uuid4()
        original(db, **kwargs)
    monkeypatch.setattr(service, "append_audit", invalid_author)

    # Act
    response = client.post("/users", json={"username": "novo", "role": "ADMIN", "password": password})

    # Assert
    assert response.status_code == 500
    assert password not in response.text + caplog.text
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(User)) == 3
        assert db.scalar(select(func.count()).select_from(AuditLog)) == 0
