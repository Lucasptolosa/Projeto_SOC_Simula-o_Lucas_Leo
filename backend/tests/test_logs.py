import json
import secrets
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateSchema, DropSchema

from app.assets.models import Asset
from app.auth.dependencies import get_auth_settings
from app.core.passwords import hash_password
from app.db.session import create_db_engine, create_session_factory, get_session
from app.logs import repository, service
from app.logs.models import LogRecord
from app.logs.schemas import LogInput
from app.main import app
from app.users.models import User


ORIGIN = "https://testserver"


def payload(asset_id, event_id="evt-1", **changes):
    return dict(event_id=event_id, asset_id=str(asset_id),
                occurred_at="2026-11-03T12:00:00Z", event_type="AUTH_FAILURE",
                username="monitored-account") | changes


@pytest.fixture
def log_context(users_db, test_db_settings):
    factory, connection = users_db
    password = secrets.token_urlsafe(24)
    with factory.begin() as db:
        admin = User(username="log-admin", role="ADMIN", password_hash=hash_password(password))
        analyst = User(username="log-analyst", role="ANALYST", password_hash=hash_password(password))
        asset = Asset(name="monitorado", type="SERVER", status="ACTIVE")
        db.add_all([admin, analyst, asset])
        db.flush()
        admin_id, analyst_id, asset_id = admin.id, analyst.id, asset.id
    settings = test_db_settings.model_copy(update={"auth_origin": ORIGIN, "auth_cookie_secure": True})
    previous = app.dependency_overrides.copy()

    def database():
        with factory() as db:
            yield db

    app.dependency_overrides[get_session] = database
    app.dependency_overrides[get_auth_settings] = lambda: settings
    try:
        with TestClient(app, base_url=ORIGIN) as client:
            login = client.post("/auth/login", json={"username": "log-admin", "password": password}, headers={"Origin": ORIGIN})
            assert login.status_code == 200
            client.headers.update({"Origin": ORIGIN, "X-CSRF-Token": login.json()["csrf_token"]})
            yield client, factory, asset_id, admin_id, analyst_id, password, connection
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def log_count(factory):
    with factory() as db:
        return db.scalar(select(func.count()).select_from(LogRecord))


@pytest.mark.parametrize("event_type", ["AUTH_FAILURE", "AUTH_SUCCESS", "ADMIN_ACCESS"])
@pytest.mark.parametrize("instant", ["2026-11-03T12:00:00Z", "2026-11-03T09:00:00-03:00"])
def test_import_persists_valid_event_and_instant(log_context, event_type, instant):
    # Arrange
    client, factory, asset_id, _, _, _, _ = log_context
    record = payload(asset_id, event_id=" Event Ç ", username=" account X ", event_type=event_type, occurred_at=instant)
    # Act
    response = client.post("/logs/import", json=[record])
    # Assert
    assert response.status_code == 200
    assert response.json() == {"accepted": 1, "rejected": 0, "rejections": []}
    assert response.headers["cache-control"] == "no-store"
    with factory() as db:
        log = db.get(LogRecord, record["event_id"])
        assert log.asset_id == asset_id and log.username == " account X "
        assert log.occurred_at == datetime(2026, 11, 3, 12, tzinfo=timezone.utc)
        assert log.event_type.value == event_type


def test_inactive_asset_and_historical_event_are_accepted(log_context):
    # Arrange
    client, factory, asset_id, _, _, _, _ = log_context
    first = payload(asset_id, occurred_at="2026-11-03T12:00:00Z")
    assert client.post("/logs/import", json=[first]).json()["accepted"] == 1
    assert client.post(f"/assets/{asset_id}/deactivate").status_code == 200
    # Act
    response = client.post("/logs/import", json=[payload(asset_id, "old-event", occurred_at="2026-01-01T00:00:00Z")])
    # Assert
    assert response.json()["accepted"] == 1
    assert log_count(factory) == 2
    with factory() as db:
        assert db.get(Asset, asset_id).status.value == "INACTIVE"
        assert db.get(LogRecord, "evt-1") is not None


@pytest.mark.parametrize("changes", [
    {"event_id": ""}, {"event_id": " \t"}, {"event_id": 1}, {"event_id": None},
    {"username": ""}, {"username": "\u2003"}, {"username": True}, {"username": None},
    {"occurred_at": "2026-11-03T12:00:00"}, {"occurred_at": "invalid"},
    {"occurred_at": 123}, {"occurred_at": True}, {"occurred_at": "123"},
    {"event_type": "ROOT"}, {"event_type": "auth_failure"}, {"event_type": None},
    {"asset_id": "invalid"}, {"extra": "private-value"},
])
def test_invalid_record_is_rejected_without_stopping_next(log_context, changes):
    # Arrange
    client, factory, asset_id, _, _, _, _ = log_context
    records = [payload(asset_id) | changes, payload(asset_id, "valid-next")]
    # Act
    response = client.post("/logs/import", json=records)
    # Assert
    assert response.status_code == 200
    result = response.json()
    assert result["accepted"] == result["rejected"] == 1
    assert result["rejections"][0]["position"] == 1
    assert "private-value" not in response.text
    assert log_count(factory) == 1


@pytest.mark.parametrize("field", ["event_id", "asset_id", "occurred_at", "event_type", "username"])
def test_missing_required_field_has_fixed_reason(log_context, field):
    # Arrange
    client, factory, asset_id, _, _, _, _ = log_context
    record = payload(asset_id)
    del record[field]
    # Act
    response = client.post("/logs/import", json=[record])
    # Assert
    assert response.json()["rejections"][0]["reason"] == "invalid_" + field
    assert log_count(factory) == 0


def test_mixed_batch_preserves_positions_and_classifies_rejections(log_context):
    # Arrange
    client, factory, asset_id, _, _, _, _ = log_context
    records = [payload(asset_id), payload(uuid4(), "missing-asset"), payload(asset_id), None, payload(asset_id, "second")]
    # Act
    response = client.post("/logs/import", json=records)
    # Assert
    result = response.json()
    assert result["accepted"] == 2 and result["rejected"] == 3
    assert [(x["position"], x["reason"]) for x in result["rejections"]] == [
        (2, "asset_not_found"), (3, "duplicate_event_id"), (4, "invalid_record"),
    ]
    assert log_count(factory) == 2


def test_duplicate_in_same_and_later_batches_keeps_original(log_context):
    # Arrange
    client, factory, asset_id, _, _, _, _ = log_context
    original = payload(asset_id)
    # Act
    first = client.post("/logs/import", json=[original, original])
    second = client.post("/logs/import", json=[original | {"username": "must-not-replace"}])
    # Assert
    assert first.json()["accepted"] == first.json()["rejected"] == 1
    assert second.json()["accepted"] == 0 and second.json()["rejected"] == 1
    with factory() as db:
        assert db.get(LogRecord, "evt-1").username == original["username"]
    assert log_count(factory) == 1


def test_all_invalid_records_return_reasons(log_context):
    # Arrange
    client, factory, _, _, _, _, _ = log_context
    # Act
    response = client.post("/logs/import", json=[None, {}, 3, "text"])
    # Assert
    assert response.status_code == 200
    assert response.json()["accepted"] == 0
    assert response.json()["rejected"] == 4
    assert len(response.json()["rejections"]) == 4
    assert log_count(factory) == 0


@pytest.mark.parametrize("size", [1, 1000])
def test_valid_batch_size_boundaries(log_context, size):
    # Arrange
    client, factory, asset_id, _, _, _, _ = log_context
    records = [payload(asset_id, f"event-{index}") for index in range(size)]
    # Act
    response = client.post("/logs/import", json=records)
    # Assert
    assert response.status_code == 200
    assert response.json()["accepted"] == size and response.json()["rejected"] == 0
    assert log_count(factory) == size


@pytest.mark.parametrize("body", [[], [None] * 1001, {}, None, "text"])
def test_invalid_outer_structure_leaves_no_data(log_context, body):
    # Arrange
    client, factory, _, _, _, _, _ = log_context
    # Act
    response = client.post("/logs/import", content=json.dumps(body), headers={"Content-Type": "application/json"})
    # Assert
    assert response.status_code == 422
    assert response.json() == {"detail": "Requisição inválida."}
    assert log_count(factory) == 0


@pytest.mark.parametrize("content_type,content,expected", [
    ("application/json", '{"secret":"private-value",', 422),
    ("text/plain", "[]", 415), ("application/octet-stream", "[]", 415),
])
def test_invalid_json_or_content_type_is_sanitized(log_context, content_type, content, expected):
    # Arrange
    client, factory, _, _, _, _, _ = log_context
    # Act
    response = client.post("/logs/import", content=content, headers={"Content-Type": content_type})
    # Assert
    assert response.status_code == expected
    assert "private-value" not in response.text
    assert log_count(factory) == 0


@pytest.mark.parametrize("mode", ["anonymous", "analyst", "csrf", "origin", "inactive", "revoked"])
def test_import_requires_admin_session_and_csrf(log_context, mode):
    # Arrange
    client, factory, asset_id, admin_id, _, password, _ = log_context
    if mode == "anonymous":
        client.cookies.clear()
    elif mode == "analyst":
        login = client.post("/auth/login", json={"username": "log-analyst", "password": password})
        client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    elif mode == "csrf":
        del client.headers["X-CSRF-Token"]
    elif mode == "origin":
        client.headers["Origin"] = "https://other.test"
    elif mode == "inactive":
        with factory.begin() as db:
            db.get(User, admin_id).status = "INACTIVE"
    else:
        assert client.post("/auth/logout").status_code == 204
    # Act
    response = client.post("/logs/import", json=[payload(asset_id)])
    # Assert
    assert response.status_code == (403 if mode in {"analyst", "csrf", "origin"} else 401)
    assert log_count(factory) == 0


def test_operational_failure_rolls_back_batch_and_hides_payload(log_context, monkeypatch, caplog):
    # Arrange
    client, factory, asset_id, _, _, _, _ = log_context
    original = repository.insert_log

    def fail_second(db, log):
        if log.event_id == "second":
            raise RuntimeError("private-value")
        return original(db, log)

    monkeypatch.setattr(repository, "insert_log", fail_second)
    # Act
    response = client.post("/logs/import", json=[payload(asset_id), payload(asset_id, "second")])
    # Assert
    assert response.status_code == 500
    assert log_count(factory) == 0
    assert "private-value" not in response.text + caplog.text
    assert "operation=/logs/import" in caplog.text and "category=RuntimeError" in caplog.text


def test_fk_preserves_logs_when_asset_deletion_is_attempted(log_context):
    # Arrange
    client, factory, asset_id, _, _, _, connection = log_context
    assert client.post("/logs/import", json=[payload(asset_id)]).json()["accepted"] == 1
    savepoint = connection.begin_nested()
    # Act
    with pytest.raises(IntegrityError):
        connection.execute(text("DELETE FROM assets WHERE id=:id"), {"id": asset_id})
    savepoint.rollback()
    # Assert
    assert log_count(factory) == 1
    with factory() as db:
        assert db.get(Asset, asset_id) is not None


def test_commit_failure_does_not_report_success(log_context):
    # Arrange
    client, factory, asset_id, _, _, _, _ = log_context

    def fail_commit(db):
        raise RuntimeError("Falha de commit simulada")

    event.listen(factory.class_, "before_commit", fail_commit)
    # Act
    try:
        response = client.post("/logs/import", json=[payload(asset_id)])
    finally:
        event.remove(factory.class_, "before_commit", fail_commit)
    # Assert
    assert response.status_code == 500
    assert "accepted" not in response.json()
    assert log_count(factory) == 0


def test_service_refusal_is_mapped_without_writes(log_context, monkeypatch):
    # Arrange
    client, factory, asset_id, _, _, _, _ = log_context

    def refuse(*args):
        raise service.LogImportError("forbidden_author")

    monkeypatch.setattr(service, "import_logs", refuse)
    # Act
    response = client.post("/logs/import", json=[payload(asset_id)])
    # Assert
    assert response.status_code == 403
    assert response.json() == {"detail": "Permissão insuficiente."}
    assert log_count(factory) == 0


@pytest.mark.parametrize("aware", [True, False])
def test_datetime_contract_requires_explicit_offset(aware):
    # Arrange
    instant = datetime(2026, 11, 3, 12, tzinfo=timezone.utc if aware else None)
    record = payload(uuid4(), occurred_at=instant)
    # Act
    if aware:
        result = LogInput.model_validate(record)
    else:
        with pytest.raises(ValidationError):
            LogInput.model_validate(record)
    # Assert
    assert record["occurred_at"] is instant
    if aware:
        assert result.occurred_at == instant


def test_rejection_logging_has_no_record_content(log_context, caplog):
    # Arrange
    client, _, asset_id, _, _, _, _ = log_context
    marker = secrets.token_urlsafe(24)
    record = payload(asset_id, occurred_at=marker)
    # Act
    response = client.post("/logs/import", json=[record])
    # Assert
    assert response.json()["rejected"] == 1
    assert marker not in response.text + caplog.text
    assert "operation=/logs/import" in caplog.text
    assert "category=RecordRejected" in caplog.text


@pytest.mark.parametrize("field,value", [("event_id", ""), ("event_id", None), ("username", "\t"), ("username", None), ("event_type", "ROOT"), ("asset_id", uuid4())])
def test_database_constraints_reject_invalid_data(log_context, field, value):
    # Arrange
    _, _, asset_id, _, _, _, connection = log_context
    values = payload(asset_id) | {"asset_id": asset_id, "occurred_at": datetime.now(timezone.utc), field: value}
    savepoint = connection.begin_nested()
    # Act
    with pytest.raises(IntegrityError):
        connection.execute(text("INSERT INTO logs(event_id,asset_id,occurred_at,event_type,username) VALUES (:event_id,:asset_id,:occurred_at,:event_type,:username)"), values)
    savepoint.rollback()
    # Assert
    assert connection.scalar(select(func.count()).select_from(LogRecord)) == 0


@pytest.mark.parametrize("actor,reason", [("missing", "inactive_author"), ("analyst", "forbidden_author"), ("inactive", "inactive_author")])
def test_service_revalidates_author(log_context, actor, reason):
    # Arrange
    _, factory, asset_id, admin_id, analyst_id, _, _ = log_context
    author_id = uuid4() if actor == "missing" else analyst_id if actor == "analyst" else admin_id
    if actor == "inactive":
        with factory.begin() as db:
            db.get(User, admin_id).status = "INACTIVE"
    # Act
    with factory() as db, pytest.raises(service.LogImportError) as error:
        service.import_logs(db, author_id, [payload(asset_id)])
    # Assert
    assert str(error.value) == reason
    assert log_count(factory) == 0


@pytest.mark.parametrize("size", [0, 1001])
def test_service_rejects_invalid_batch_size(log_context, size):
    # Arrange
    _, factory, _, admin_id, _, _, _ = log_context
    # Act
    with factory() as db, pytest.raises(service.LogImportError) as error:
        service.import_logs(db, admin_id, [None] * size)
    # Assert
    assert str(error.value) == "invalid_batch_size"
    assert log_count(factory) == 0


def test_concurrent_duplicate_has_single_winner(test_db_settings):
    # Arrange
    engine = create_db_engine(test_db_settings)
    schema = "test_logs_race_" + uuid4().hex
    asset_id = uuid4()
    barrier = Barrier(2)
    created = False
    try:
        with engine.begin() as connection:
            assert connection.scalar(text("SELECT current_database()")) == "mini_soc_test"
            connection.execute(CreateSchema(schema))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            connection.execute(Asset.__table__.insert().values(id=asset_id, name="race", type="SERVER", status="ACTIVE"))
        created = True

        def competitor():
            with engine.begin() as connection:
                assert connection.scalar(text("SELECT current_database()")) == "mini_soc_test"
                connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                with create_session_factory(connection)() as db:
                    barrier.wait(timeout=5)
                    return repository.insert_log(db, LogInput.model_validate(payload(asset_id)))

        # Act
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(competitor)
            second = pool.submit(competitor)
            results = [first.result(timeout=15), second.result(timeout=15)]
        # Assert
        assert sorted(results) == [False, True]
        with engine.begin() as connection:
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            assert connection.scalar(select(func.count()).select_from(LogRecord)) == 1
    finally:
        if created:
            with engine.begin() as connection:
                assert connection.scalar(text("SELECT current_database()")) == "mini_soc_test"
                assert schema.startswith("test_logs_race_") and len(schema) == 47
                connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()
