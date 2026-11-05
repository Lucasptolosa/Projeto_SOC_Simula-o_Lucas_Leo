from datetime import datetime, timezone
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, func, inspect, select
from sqlalchemy.exc import IntegrityError

from app.audit.models import AuditLog
from app.auth.service import COOKIE_NAME
from app.detection.models import AlertLog, AlertRecord
from app.investigations import service
from app.investigations.models import Investigation, Observation
from app.investigations.rules import InvestigationRuleError
from app.logs.models import LogRecord
from app.users.models import User
from test_detection_persistence import record
from test_logs import log_context, ORIGIN


def login(client, username, password):
    response = client.post("/auth/login", json={"username": username, "password": password},
                           headers={"Origin": ORIGIN})
    assert response.status_code == 200
    client.headers["X-CSRF-Token"] = response.json()["csrf_token"]


@pytest.fixture
def investigation_context(log_context):
    client, factory, asset_id, admin_id, analyst_id, password, connection = log_context
    response = client.post("/logs/import", json=[record(asset_id, n, n) for n in range(5)])
    assert response.json()["detection"]["alerts_created"] == 1
    with factory() as db:
        alert_id = db.scalar(select(AlertRecord.id))
    login(client, "log-analyst", password)
    return client, factory, alert_id, analyst_id, admin_id, password, connection


def start(client, alert_id):
    response = client.post("/investigations", json={"alert_id": str(alert_id)})
    assert response.status_code == 201
    return response.json()["id"]


def count(factory, model):
    with factory() as db:
        return db.scalar(select(func.count()).select_from(model))


def with_instants(body):
    return {key: datetime.fromisoformat(value.replace("Z", "+00:00"))
            if key.endswith("_at") and value is not None else value
            for key, value in body.items()}


def evidence(factory):
    with factory() as db:
        return (
            [tuple(getattr(row, c.name) for c in LogRecord.__table__.columns)
             for row in db.scalars(select(LogRecord).order_by(LogRecord.event_id))],
            [tuple(getattr(row, c.name) for c in AlertLog.__table__.columns)
             for row in db.scalars(select(AlertLog).order_by(AlertLog.position))],
        )


def test_start_persists_and_recovers(investigation_context):
    # Arrange
    client, factory, alert_id, analyst_id, *_ = investigation_context
    before = datetime.now(timezone.utc)
    # Act
    response = client.post("/investigations", json={"alert_id": str(alert_id)})
    recovered = client.get("/investigations/" + response.json()["id"])
    # Assert
    assert response.status_code == 201 and with_instants(recovered.json()) == with_instants(response.json())
    body = response.json()
    assert UUID(body["analyst_id"]) == analyst_id and UUID(body["alert_id"]) == alert_id
    assert body["status"] == "IN_REVIEW" and body["justification"] is None
    assert datetime.fromisoformat(body["started_at"].replace("Z", "+00:00")) >= before
    assert response.headers["cache-control"] == "no-store"
    with factory() as db:
        assert db.get(AlertRecord, alert_id).status == "IN_REVIEW"
        assert db.get(Investigation, UUID(body["id"])).analyst_id == analyst_id
    assert count(factory, AuditLog) == 0


@pytest.mark.parametrize("status", ["IN_REVIEW", "DISMISSED", "ESCALATED"])
def test_start_rejects_invalid_status(investigation_context, status):
    # Arrange
    client, factory, alert_id, *_ = investigation_context
    with factory.begin() as db:
        db.get(AlertRecord, alert_id).status = status
    # Act
    response = client.post("/investigations", json={"alert_id": str(alert_id)})
    # Assert
    assert response.status_code == 409 and count(factory, Investigation) == 0
    with factory() as db:
        assert db.get(AlertRecord, alert_id).status == status


def test_start_missing_alert(investigation_context):
    # Arrange
    client, factory, *_ = investigation_context
    # Act
    response = client.post("/investigations", json={"alert_id": str(uuid4())})
    # Assert
    assert response.status_code == 404 and count(factory, Investigation) == 0


def test_repeated_start_preserves_author_and_instant(investigation_context):
    # Arrange
    client, factory, alert_id, *_ = investigation_context
    identifier = start(client, alert_id)
    original = client.get(f"/investigations/{identifier}").json()
    # Act
    response = client.post("/investigations", json={"alert_id": str(alert_id)})
    # Assert
    assert response.status_code == 409 and count(factory, Investigation) == 1
    assert client.get(f"/investigations/{identifier}").json() == original


@pytest.mark.parametrize("content", ["x", "  Evidência legítima.\nRevisão concluída.  ", "ç" * 6000])
def test_observations_preserve_text_and_author(investigation_context, content):
    # Arrange
    client, factory, alert_id, analyst_id, *_ = investigation_context
    identifier = start(client, alert_id)
    before = evidence(factory)
    # Act
    response = client.post(f"/investigations/{identifier}/observations", json={"content": content})
    recovered = client.get(f"/investigations/{identifier}/observations").json()
    # Assert
    assert response.status_code == 201 and recovered["total"] == 1
    assert [with_instants(row) for row in recovered["items"]] == [with_instants(response.json())]
    assert response.json()["content"] == content
    assert UUID(response.json()["analyst_id"]) == analyst_id
    assert datetime.fromisoformat(response.json()["occurred_at"].replace("Z", "+00:00")).tzinfo
    with factory() as db:
        assert db.get(Observation, UUID(response.json()["id"])).content == content
    assert evidence(factory) == before and count(factory, AuditLog) == 0


@pytest.mark.parametrize("operation,field", [("observations", "content"), ("false-positive", "justification")])
@pytest.mark.parametrize("value", [None, "", " \t\n\u2003", 123, [], {}, "a\x00b", "\ud800"])
def test_invalid_text_is_rejected_without_echo(investigation_context, operation, field, value, caplog):
    # Arrange
    client, factory, alert_id, *_ = investigation_context
    identifier = start(client, alert_id)
    payload = json.dumps({field: value}, ensure_ascii=True)
    # Act
    response = client.post(f"/investigations/{identifier}/{operation}", content=payload,
                           headers={"Content-Type": "application/json"})
    # Assert
    assert response.status_code == 422 and response.json() == {"detail": "Requisição inválida."}
    assert count(factory, Observation) == count(factory, AuditLog) == 0
    assert client.get(f"/investigations/{identifier}").json()["status"] == "IN_REVIEW"
    assert payload not in response.text + caplog.text


@pytest.mark.parametrize("method,path,body", [
    ("post", "/investigations", {}),
    ("post", "/investigations", {"alert_id": "invalid-private-value"}),
    ("post", "/investigations", {"alert_id": str(uuid4()), "extra": "private-value"}),
    ("get", "/investigations/invalid-private-value", None),
    ("post", "/investigations/{id}/observations", {}),
    ("post", "/investigations/{id}/observations", {"content": "x", "author_id": "private-value"}),
    ("post", "/investigations/{id}/false-positive", {}),
])
def test_invalid_contracts(investigation_context, method, path, body):
    # Arrange
    client, factory, alert_id, *_ = investigation_context
    identifier = start(client, alert_id)
    # Act
    response = client.request(method, path.format(id=identifier), json=body)
    # Assert
    assert response.status_code == 422
    assert "private-value" not in response.text
    assert count(factory, Observation) == count(factory, AuditLog) == 0


OPERATIONS = [
    ("post", "/investigations", "start"),
    ("get", "/investigations/{id}", "read"),
    ("post", "/investigations/{id}/observations", "note"),
    ("get", "/investigations/{id}/observations", "notes"),
    ("post", "/investigations/{id}/false-positive", "dismiss"),
]


def request_body(operation, alert_id):
    return {"alert_id": str(alert_id)} if operation == "start" else (
        {"content": "note"} if operation == "note" else {"justification": "legitimate"})


@pytest.mark.parametrize("method,path,operation", OPERATIONS)
@pytest.mark.parametrize("actor,expected", [("admin", 403), ("anonymous", 401), ("inactive", 401)])
def test_only_active_analyst(investigation_context, method, path, operation, actor, expected):
    # Arrange
    client, factory, alert_id, analyst_id, _, password, _ = investigation_context
    identifier = start(client, alert_id)
    if actor == "admin":
        login(client, "log-admin", password)
    elif actor == "anonymous":
        client.cookies.clear()
    else:
        with factory.begin() as db:
            db.get(User, analyst_id).status = "INACTIVE"
    # Act
    response = client.request(method, path.format(id=identifier), json=request_body(operation, alert_id))
    # Assert
    assert response.status_code == expected
    assert count(factory, Investigation) == 1
    assert count(factory, Observation) == count(factory, AuditLog) == 0
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("operation", ["start", "note", "dismiss"])
@pytest.mark.parametrize("header", ["Origin", "X-CSRF-Token"])
def test_writes_require_origin_and_csrf(investigation_context, operation, header):
    # Arrange
    client, factory, alert_id, *_ = investigation_context
    identifier = start(client, alert_id)
    path = "/investigations" if operation == "start" else f"/investigations/{identifier}/" + (
        "observations" if operation == "note" else "false-positive")
    client.headers.pop(header)
    # Act
    response = client.post(path, json=request_body(operation, alert_id))
    # Assert
    assert response.status_code == 403
    assert count(factory, Observation) == count(factory, AuditLog) == 0


@pytest.mark.parametrize("method,path,operation", OPERATIONS[1:])
def test_missing_investigation(investigation_context, method, path, operation):
    # Arrange
    client, factory, alert_id, *_ = investigation_context
    # Act
    response = client.request(method, path.format(id=uuid4()), json=request_body(operation, alert_id))
    # Assert
    assert response.status_code == 404
    assert count(factory, Observation) == count(factory, AuditLog) == 0


def test_false_positive_is_atomic_and_audited(investigation_context):
    # Arrange
    client, factory, alert_id, analyst_id, _, password, connection = investigation_context
    identifier = start(client, alert_id)
    before = evidence(factory)
    justification = "  Acesso autorizado.\nEvidência verificada.  "
    # Act
    response = client.post(f"/investigations/{identifier}/false-positive", json={"justification": justification})
    recovered = client.get(f"/investigations/{identifier}").json()
    # Assert
    assert response.status_code == 200 and with_instants(recovered) == with_instants(response.json())
    assert recovered["status"] == "DISMISSED" and recovered["justification"] == justification
    assert UUID(recovered["dismissed_by"]) == analyst_id
    with factory() as db:
        row = db.get(Investigation, UUID(identifier))
        audit = db.scalar(select(AuditLog))
        assert row.justification == justification and db.get(AlertRecord, alert_id).status == "DISMISSED"
        assert (audit.author_id, audit.action, audit.entity_type, audit.entity_id) == (
            analyst_id, "ALERT_DISMISSED", "ALERT", str(alert_id))
        assert (audit.old_status, audit.new_status) == ("IN_REVIEW", "DISMISSED")
        assert audit.old_role is audit.new_role is None and audit.occurred_at == row.dismissed_at
    assert evidence(factory) == before and "incidents" not in inspect(connection).get_table_names()
    login(client, "log-admin", password)
    public_audit = client.get("/audit-logs").json()["items"][0]
    assert public_audit["old_status"] == "IN_REVIEW" and public_audit["new_status"] == "DISMISSED"


@pytest.mark.parametrize("status", ["NEW", "DISMISSED", "ESCALATED"])
def test_false_positive_rejects_other_states(investigation_context, status):
    # Arrange
    client, factory, alert_id, *_ = investigation_context
    identifier = start(client, alert_id)
    with factory.begin() as db:
        db.get(AlertRecord, alert_id).status = status
    # Act
    response = client.post(f"/investigations/{identifier}/false-positive", json={"justification": "legitimate"})
    # Assert
    assert response.status_code == 409 and count(factory, AuditLog) == 0
    assert client.get(f"/investigations/{identifier}").json()["justification"] is None


def test_repeated_dismissal_does_not_overwrite(investigation_context):
    # Arrange
    client, factory, alert_id, *_ = investigation_context
    identifier = start(client, alert_id)
    first = client.post(f"/investigations/{identifier}/false-positive", json={"justification": "first"})
    # Act
    repeated = client.post(f"/investigations/{identifier}/false-positive", json={"justification": "second"})
    # Assert
    assert first.status_code == 200 and repeated.status_code == 409
    assert with_instants(client.get(f"/investigations/{identifier}").json()) == with_instants(first.json())
    assert count(factory, AuditLog) == 1


def test_observation_after_dismissal_preserves_terminal_status(investigation_context):
    # Arrange
    client, factory, alert_id, *_ = investigation_context
    identifier = start(client, alert_id)
    client.post(f"/investigations/{identifier}/false-positive", json={"justification": "legitimate"})
    # Act
    response = client.post(f"/investigations/{identifier}/observations", json={"content": "Complemento técnico."})
    # Assert
    assert response.status_code == 201
    assert client.get(f"/investigations/{identifier}").json()["status"] == "DISMISSED"
    assert count(factory, AuditLog) == 1


def test_notes_are_paginated_with_deterministic_ties(investigation_context):
    # Arrange
    client, factory, alert_id, analyst_id, *_ = investigation_context
    identifier = start(client, alert_id)
    with factory.begin() as db:
        db.add_all([Observation(id=UUID(int=n), investigation_id=UUID(identifier),
            analyst_id=analyst_id, content=str(n), occurred_at=datetime(2026, 11, 1, tzinfo=timezone.utc))
            for n in [3, 1, 2]])
    # Act
    pages = [client.get(f"/investigations/{identifier}/observations", params={"page": n, "page_size": 1}).json()
             for n in [1, 2, 3, 4, 10000]]
    # Assert
    assert [[row["content"] for row in page["items"]] for page in pages] == [["1"], ["2"], ["3"], [], []]
    assert all(page["total"] == 3 for page in pages)
    assert count(factory, AuditLog) == 0


@pytest.mark.parametrize("params", [{"page": 0}, {"page": 10001}, {"page_size": 0}, {"page_size": 101}, {"extra": "private"}])
def test_invalid_pagination(investigation_context, params):
    # Arrange
    client, factory, alert_id, *_ = investigation_context
    identifier = start(client, alert_id)
    # Act
    response = client.get(f"/investigations/{identifier}/observations", params=params)
    # Assert
    assert response.status_code == 422 and count(factory, Observation) == 0
    assert response.json() == {"detail": "Requisição inválida."}


@pytest.mark.parametrize("operation", ["start", "note", "dismiss"])
def test_commit_failure_rolls_back_operation(investigation_context, operation, caplog):
    # Arrange
    client, factory, alert_id, *_ = investigation_context
    identifier = start(client, alert_id) if operation != "start" else None
    def fail(db):
        raise RuntimeError("private-commit-value")
    event.listen(factory.class_, "before_commit", fail)
    path = "/investigations" if operation == "start" else f"/investigations/{identifier}/" + (
        "observations" if operation == "note" else "false-positive")
    # Act
    try:
        response = client.post(path, json=request_body(operation, alert_id))
    finally:
        event.remove(factory.class_, "before_commit", fail)
    # Assert
    assert response.status_code == 500 and "private-commit-value" not in response.text + caplog.text
    assert count(factory, Investigation) == (0 if operation == "start" else 1)
    assert count(factory, Observation) == count(factory, AuditLog) == 0
    with factory() as db:
        assert db.get(AlertRecord, alert_id).status == ("NEW" if operation == "start" else "IN_REVIEW")
        if identifier:
            assert db.get(Investigation, UUID(identifier)).justification is None


def test_audit_failure_rolls_back_dismissal(investigation_context, monkeypatch, caplog):
    # Arrange
    client, factory, alert_id, *_ = investigation_context
    identifier = start(client, alert_id)
    def fail(*args, **kwargs):
        raise RuntimeError("private-audit-value")
    monkeypatch.setattr(service, "append_audit", fail)
    # Act
    response = client.post(f"/investigations/{identifier}/false-positive", json={"justification": "legitimate"})
    # Assert
    assert response.status_code == 500
    assert client.get(f"/investigations/{identifier}").json()["status"] == "IN_REVIEW"
    assert count(factory, AuditLog) == 0 and "private-audit-value" not in caplog.text


def test_secrets_are_not_exposed(investigation_context, caplog):
    # Arrange
    client, factory, alert_id, analyst_id, _, password, _ = investigation_context
    token = client.cookies.get(COOKIE_NAME)
    with factory() as db:
        encoded = db.get(User, analyst_id).password_hash
    # Act
    identifier = start(client, alert_id)
    responses = [client.get(f"/investigations/{identifier}"), client.get(f"/investigations/{identifier}/observations")]
    # Assert
    for response in responses:
        assert all(secret not in response.text + caplog.text for secret in [password, token, encoded])
        assert "password_hash" not in response.text and response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("change,expected", [("missing", "inactive_author"), ("inactive", "inactive_author"), ("role", "forbidden_author")])
def test_service_rechecks_actor(investigation_context, change, expected):
    # Arrange
    _, factory, alert_id, analyst_id, *_ = investigation_context
    with factory.begin() as db:
        if change == "inactive":
            db.get(User, analyst_id).status = "INACTIVE"
        elif change == "role":
            db.get(User, analyst_id).role = "ADMIN"
    author = uuid4() if change == "missing" else analyst_id
    # Act
    with factory() as db, pytest.raises(service.InvestigationServiceError) as error:
        service.start(db, author, alert_id)
    # Assert
    assert str(error.value) == expected and count(factory, Investigation) == 0


def test_database_preserves_uniqueness_and_references(investigation_context):
    # Arrange
    client, factory, alert_id, analyst_id, *_ = investigation_context
    identifier = start(client, alert_id)
    # Act
    with pytest.raises(IntegrityError), factory.begin() as db:
        db.add(Investigation(alert_id=alert_id, analyst_id=analyst_id, started_at=datetime.now(timezone.utc)))
    with pytest.raises(IntegrityError), factory.begin() as db:
        db.add(Observation(investigation_id=uuid4(), analyst_id=analyst_id, content="note", occurred_at=datetime.now(timezone.utc)))
    # Assert
    assert count(factory, Investigation) == 1 and count(factory, Observation) == 0
    assert client.get(f"/investigations/{identifier}").status_code == 200
