import secrets
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError

from app.assets import service
from app.assets.models import Asset, AssetStatus
from app.audit.models import AuditLog
from app.auth.dependencies import get_auth_settings
from app.core.passwords import hash_password
from app.db.session import get_session
from app.main import app
from app.users.models import User


ORIGIN = "https://testserver"
VALID = {"name": " Servidor São Paulo ", "type": "SERVER", "status": "ACTIVE"}


@pytest.fixture
def assets_context(users_db, test_db_settings):
    factory, connection = users_db
    password = secrets.token_urlsafe(24)
    encoded = hash_password(password)
    ids = {}
    with factory.begin() as db:
        for name, role in [("asset-admin", "ADMIN"), ("asset-analyst", "ANALYST")]:
            user = User(username=name, role=role, password_hash=encoded)
            db.add(user)
            db.flush()
            ids[name] = user.id
    previous = app.dependency_overrides.copy()
    settings = test_db_settings.model_copy(update={"auth_origin": ORIGIN, "auth_cookie_secure": True})

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_session] = database
    app.dependency_overrides[get_auth_settings] = lambda: settings
    try:
        with TestClient(app, base_url=ORIGIN) as client:
            login = client.post("/auth/login", json={"username": "asset-admin", "password": password}, headers={"Origin": ORIGIN})
            assert login.status_code == 200
            client.headers.update({"Origin": ORIGIN, "X-CSRF-Token": login.json()["csrf_token"]})
            yield client, factory, ids, password, connection
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def count_rows(factory, model):
    with factory() as db:
        return db.scalar(select(func.count()).select_from(model))


@pytest.mark.parametrize("kind", ["SERVER", "WORKSTATION", "APPLICATION"])
@pytest.mark.parametrize("status", ["ACTIVE", "INACTIVE"])
def test_create_persists_asset_and_exact_audit(assets_context, kind, status):
    # Arrange
    client, factory, ids, _, _ = assets_context
    before = datetime.now(timezone.utc)
    # Act
    response = client.post("/assets", json=VALID | {"type": kind, "status": status})
    # Assert
    assert response.status_code == 201
    result = response.json()
    assert set(result) == {"id", "name", "type", "status"}
    assert result == VALID | {"id": result["id"], "type": kind, "status": status}
    assert response.headers["cache-control"] == "no-store"
    with factory() as db:
        asset = db.get(Asset, UUID(result["id"]))
        audit = db.scalar(select(AuditLog))
        assert asset.name == VALID["name"]
        assert audit.author_id == ids["asset-admin"]
        assert audit.action == "ASSET_CREATED" and audit.entity_type == "ASSET"
        assert audit.entity_id == str(asset.id)
        assert before <= audit.occurred_at <= datetime.now(timezone.utc)
        assert audit.old_role is None and audit.new_role is None
    assert count_rows(factory, AuditLog) == 1


def test_equal_names_keep_distinct_identity(assets_context):
    # Arrange
    client, factory, _, _, _ = assets_context
    # Act
    first = client.post("/assets", json=VALID)
    second = client.post("/assets", json=VALID)
    # Assert
    assert first.status_code == second.status_code == 201
    assert first.json()["id"] != second.json()["id"]
    assert count_rows(factory, Asset) == count_rows(factory, AuditLog) == 2


@pytest.mark.parametrize("initial_status", ["ACTIVE", "INACTIVE"])
@pytest.mark.parametrize("changes", [{"name": "novo"}, {"type": "APPLICATION"}, {"name": "novo", "type": "WORKSTATION"}])
def test_update_preserves_identity_status_and_history(assets_context, initial_status, changes):
    # Arrange
    client, factory, _, _, _ = assets_context
    original = client.post("/assets", json=VALID | {"status": initial_status}).json()
    with factory() as db:
        first_audit = db.scalar(select(AuditLog.id))
    # Act
    response = client.patch("/assets/" + original["id"], json=changes)
    # Assert
    assert response.status_code == 200
    assert response.json() == original | changes
    with factory() as db:
        assert db.get(AuditLog, first_audit).action == "ASSET_CREATED"
        assert db.scalar(select(AuditLog).where(AuditLog.action == "ASSET_UPDATED")).entity_id == original["id"]
    assert count_rows(factory, Asset) == 1
    assert count_rows(factory, AuditLog) == 2


def test_deactivate_is_idempotent_and_preserves_history(assets_context):
    # Arrange
    client, factory, _, _, _ = assets_context
    original = client.post("/assets", json=VALID).json()
    # Act
    first = client.post(f"/assets/{original['id']}/deactivate")
    second = client.post(f"/assets/{original['id']}/deactivate")
    unchanged = client.patch(f"/assets/{original['id']}", json={"name": original["name"]})
    # Assert
    assert first.status_code == second.status_code == unchanged.status_code == 200
    assert first.json() == second.json() == unchanged.json() == original | {"status": "INACTIVE"}
    assert count_rows(factory, Asset) == 1
    with factory() as db:
        actions = db.scalars(select(AuditLog.action).order_by(AuditLog.occurred_at)).all()
        assert actions == ["ASSET_CREATED", "ASSET_DEACTIVATED"]


@pytest.mark.parametrize("changes", [{}, {"name": None}, {"type": None}, {"name": "\t"}, {"type": "ROOT"}, {"status": "INACTIVE"}, {"id": str(uuid4())}])
def test_invalid_update_does_not_mutate_or_audit(assets_context, changes):
    # Arrange
    client, factory, _, _, _ = assets_context
    asset_id = UUID(client.post("/assets", json=VALID).json()["id"])
    # Act
    response = client.patch(f"/assets/{asset_id}", json=changes)
    # Assert
    assert response.status_code == 422
    assert count_rows(factory, AuditLog) == 1
    with factory() as db:
        assert db.get(Asset, asset_id).name == VALID["name"]
        assert db.get(Asset, asset_id).status is AssetStatus.ACTIVE


@pytest.mark.parametrize("body", [{}, VALID | {"name": ""}, VALID | {"status": None}, VALID | {"type": "ROOT"}, VALID | {"id": str(uuid4())}])
def test_invalid_create_leaves_no_asset_or_audit(assets_context, body):
    # Arrange
    client, factory, _, _, _ = assets_context
    # Act
    response = client.post("/assets", json=body)
    # Assert
    assert response.status_code == 422
    assert count_rows(factory, Asset) == count_rows(factory, AuditLog) == 0


@pytest.mark.parametrize("operation", ["update", "deactivate"])
def test_unknown_asset_returns_404_without_audit(assets_context, operation):
    # Arrange
    client, factory, _, _, _ = assets_context
    path = f"/assets/{uuid4()}"
    # Act
    response = client.patch(path, json={"name": "novo"}) if operation == "update" else client.post(path + "/deactivate")
    # Assert
    assert response.status_code == 404
    assert count_rows(factory, Asset) == count_rows(factory, AuditLog) == 0


@pytest.mark.parametrize("operation", ["create", "update", "deactivate"])
@pytest.mark.parametrize("mode", ["anonymous", "analyst", "csrf", "origin", "inactive", "revoked"])
def test_every_write_requires_authorized_session(assets_context, operation, mode):
    # Arrange
    client, factory, ids, password, _ = assets_context
    asset_id = client.post("/assets", json=VALID).json()["id"]
    if mode == "anonymous":
        client.cookies.clear()
    elif mode == "analyst":
        response = client.post("/auth/login", json={"username": "asset-analyst", "password": password})
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
    elif mode == "csrf":
        del client.headers["X-CSRF-Token"]
    elif mode == "origin":
        client.headers["Origin"] = "https://other.test"
    elif mode == "inactive":
        with factory.begin() as db:
            db.get(User, ids["asset-admin"]).status = "INACTIVE"
    elif mode == "revoked":
        assert client.post("/auth/logout").status_code == 204
    # Act
    if operation == "create":
        result = client.post("/assets", json=VALID)
    elif operation == "update":
        result = client.patch(f"/assets/{asset_id}", json={"name": "blocked"})
    else:
        result = client.post(f"/assets/{asset_id}/deactivate")
    # Assert
    assert result.status_code == (403 if mode in {"analyst", "csrf", "origin"} else 401)
    assert count_rows(factory, Asset) == count_rows(factory, AuditLog) == 1
    with factory() as db:
        asset = db.get(Asset, UUID(asset_id))
        assert asset.name == VALID["name"] and asset.status is AssetStatus.ACTIVE


@pytest.mark.parametrize("operation", ["create", "update", "deactivate"])
def test_audit_failure_rolls_back_both_writes(assets_context, monkeypatch, operation):
    # Arrange
    client, factory, _, _, _ = assets_context
    asset_id = UUID(client.post("/assets", json=VALID).json()["id"])
    original_append = service.append_audit

    def fail_audit(db, **kwargs):
        original_append(db, **kwargs)
        db.flush()
        raise RuntimeError("Falha simulada")

    monkeypatch.setattr(service, "append_audit", fail_audit)
    # Act
    if operation == "create":
        result = client.post("/assets", json=VALID)
    elif operation == "update":
        result = client.patch(f"/assets/{asset_id}", json={"name": "rollback"})
    else:
        result = client.post(f"/assets/{asset_id}/deactivate")
    # Assert
    assert result.status_code == 500
    assert "Falha simulada" not in result.text
    assert count_rows(factory, Asset) == count_rows(factory, AuditLog) == 1
    with factory() as db:
        asset = db.get(Asset, asset_id)
        assert asset.name == VALID["name"] and asset.status is AssetStatus.ACTIVE


@pytest.mark.parametrize("author_kind,expected", [("missing", "inactive_author"), ("analyst", "forbidden_author"), ("inactive", "inactive_author")])
def test_service_rechecks_current_author(assets_context, author_kind, expected):
    # Arrange
    _, factory, ids, _, _ = assets_context
    author_id = uuid4() if author_kind == "missing" else ids["asset-analyst"] if author_kind == "analyst" else ids["asset-admin"]
    if author_kind == "inactive":
        with factory.begin() as db:
            db.get(User, author_id).status = "INACTIVE"
    # Act
    with factory() as db, pytest.raises(service.AssetRuleError) as error:
        service.create_asset(db, author_id, "servidor", "SERVER", "ACTIVE")
    # Assert
    assert str(error.value) == expected
    assert count_rows(factory, Asset) == count_rows(factory, AuditLog) == 0


@pytest.mark.parametrize("field,value", [("name", ""), ("name", " \t"), ("name", None), ("type", "ROOT"), ("type", None), ("status", "REMOVED"), ("status", None)])
def test_database_rejects_invalid_asset(users_db, field, value):
    # Arrange
    _, connection = users_db
    values = {"id": uuid4(), **VALID, field: value}
    transaction = connection.begin_nested()
    # Act
    with pytest.raises(IntegrityError):
        connection.execute(text("INSERT INTO assets (id, name, type, status) VALUES (:id, :name, :type, :status)"), values)
    transaction.rollback()
    # Assert
    assert connection.scalar(select(func.count()).select_from(Asset)) == 0


def test_asset_constraint_failure_creates_no_audit(assets_context):
    # Arrange
    client, factory, _, _, _ = assets_context

    def corrupt_name(mapper, connection, target):
        target.__dict__["name"] = None

    event.listen(Asset, "before_insert", corrupt_name)
    # Act
    try:
        response = client.post("/assets", json=VALID)
    finally:
        event.remove(Asset, "before_insert", corrupt_name)
    # Assert
    assert response.status_code == 500
    assert count_rows(factory, Asset) == count_rows(factory, AuditLog) == 0


def test_audit_constraint_failure_reverts_asset(assets_context, monkeypatch):
    # Arrange
    client, factory, _, _, _ = assets_context
    original_append = service.append_audit

    def invalid_author(db, **kwargs):
        kwargs["author_id"] = uuid4()
        original_append(db, **kwargs)

    monkeypatch.setattr(service, "append_audit", invalid_author)
    # Act
    response = client.post("/assets", json=VALID)
    # Assert
    assert response.status_code == 500
    assert count_rows(factory, Asset) == count_rows(factory, AuditLog) == 0
