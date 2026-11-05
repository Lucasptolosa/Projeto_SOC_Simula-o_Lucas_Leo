from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select, text
from sqlalchemy.exc import IntegrityError

from app.audit.models import AuditLog
from app.auth.service import COOKIE_NAME
from app.detection.models import AlertRecord
from app.incidents import service
from app.incidents.models import Incident
from app.incidents.transitions import IncidentStatus
from app.investigations.models import Investigation, Observation
from app.users.models import User
from test_investigations import investigation_context, start, count, evidence, login, with_instants
from test_logs import log_context


@pytest.fixture
def escalation(investigation_context):
    client, factory, alert_id, analyst_id, admin_id, password, connection = investigation_context
    identifier = start(client, alert_id)
    return client, factory, alert_id, identifier, analyst_id, admin_id, password, connection


def escalate(client, identifier):
    return client.post(f"/investigations/{identifier}/escalate")


@pytest.mark.parametrize("severity", ["LOW", "MEDIUM", "HIGH", "CRITICAL"])
def test_escalation_persists_inherited_severity_and_audit(escalation, severity):
    # Arrange
    client, factory, alert_id, identifier, analyst_id, *_ = escalation
    with factory.begin() as db:
        db.get(AlertRecord, alert_id).severity = severity
    before = evidence(factory)
    client.post(f"/investigations/{identifier}/observations", json={"content": "preserved evidence"})
    original = client.get(f"/investigations/{identifier}").json()
    # Act
    response = escalate(client, identifier)
    recovered = client.get("/incidents/" + response.json()["id"])
    # Assert
    assert response.status_code == 201 and recovered.status_code == 200
    assert with_instants(response.json()) == with_instants(recovered.json())
    body = response.json()
    assert body["status"] == "OPEN" and body["severity"] == severity
    assert UUID(body["alert_id"]) == alert_id and UUID(body["analyst_id"]) == analyst_id
    assert response.headers["cache-control"] == recovered.headers["cache-control"] == "no-store"
    with factory() as db:
        incident = db.get(Incident, UUID(body["id"]))
        audit = db.scalar(select(AuditLog))
        assert incident.status is IncidentStatus.OPEN and incident.severity == severity
        assert db.get(AlertRecord, alert_id).status == "ESCALATED"
        assert (audit.action, audit.author_id, audit.entity_type, audit.entity_id) == (
            "ALERT_ESCALATED", analyst_id, "ALERT", str(alert_id))
        assert (audit.old_status, audit.new_status) == ("IN_REVIEW", "ESCALATED")
        assert audit.old_role is audit.new_role is None and audit.occurred_at == incident.opened_at
        assert db.get(Investigation, UUID(identifier)).analyst_id == analyst_id
    after = client.get(f"/investigations/{identifier}").json()
    assert after == original | {"status": "ESCALATED"}
    assert count(factory, Incident) == count(factory, AuditLog) == count(factory, Observation) == 1
    assert evidence(factory) == before


def test_get_does_not_recalculate_severity(escalation):
    # Arrange
    client, factory, alert_id, identifier, *_ = escalation
    response = escalate(client, identifier)
    with factory.begin() as db:
        db.get(AlertRecord, alert_id).severity = "LOW"
    # Act
    recovered = client.get("/incidents/" + response.json()["id"])
    # Assert
    assert recovered.json()["severity"] == response.json()["severity"] == "HIGH"
    assert count(factory, AuditLog) == 1


@pytest.mark.parametrize("status", ["NEW", "DISMISSED", "ESCALATED"])
def test_incompatible_alert_status_preserves_history(escalation, status):
    # Arrange
    client, factory, alert_id, identifier, *_ = escalation
    with factory.begin() as db:
        db.get(AlertRecord, alert_id).status = status
    original = client.get(f"/investigations/{identifier}").json()
    # Act
    response = escalate(client, identifier)
    # Assert
    assert response.status_code == 409 and count(factory, Incident) == count(factory, AuditLog) == 0
    assert client.get(f"/investigations/{identifier}").json() == original


def test_existing_alert_without_investigation_cannot_escalate(investigation_context):
    # Arrange
    client, factory, alert_id, *_ = investigation_context
    with factory.begin() as db:
        db.get(AlertRecord, alert_id).status = "IN_REVIEW"
    # Act
    response = escalate(client, str(alert_id))
    # Assert
    assert response.status_code == 404 and count(factory, Investigation) == count(factory, Incident) == 0
    with factory() as db:
        assert db.get(AlertRecord, alert_id).status == "IN_REVIEW"


def test_missing_investigation(escalation):
    # Arrange
    client, factory, *_ = escalation
    # Act
    response = escalate(client, str(uuid4()))
    # Assert
    assert response.status_code == 404 and count(factory, Incident) == count(factory, AuditLog) == 0


def test_repetition_preserves_incident_identity(escalation):
    # Arrange
    client, factory, _, identifier, *_ = escalation
    first = escalate(client, identifier)
    # Act
    repeated = escalate(client, identifier)
    # Assert
    assert first.status_code == 201 and repeated.status_code == 409
    assert count(factory, Incident) == count(factory, AuditLog) == 1
    assert with_instants(client.get("/incidents/" + first.json()["id"]).json()) == with_instants(first.json())


def test_duplicate_guard_does_not_depend_only_on_status(escalation):
    # Arrange
    client, factory, alert_id, identifier, *_ = escalation
    original = escalate(client, identifier).json()
    with factory.begin() as db:
        db.get(AlertRecord, alert_id).status = "IN_REVIEW"
    # Act
    response = escalate(client, identifier)
    # Assert
    assert response.status_code == 409 and count(factory, Incident) == count(factory, AuditLog) == 1
    assert with_instants(client.get("/incidents/" + original["id"]).json()) == with_instants(original)


@pytest.mark.parametrize("read", [False, True])
@pytest.mark.parametrize("actor,expected", [("admin", 403), ("anonymous", 401), ("inactive", 401)])
def test_only_active_analyst(escalation, actor, expected, read):
    # Arrange
    client, factory, _, identifier, analyst_id, _, password, _ = escalation
    original = escalate(client, identifier)
    if actor == "admin":
        login(client, "log-admin", password)
    elif actor == "anonymous":
        client.cookies.clear()
    else:
        with factory.begin() as db:
            db.get(User, analyst_id).status = "INACTIVE"
    # Act
    response = client.get("/incidents/" + original.json()["id"]) if read else escalate(client, identifier)
    # Assert
    assert response.status_code == expected
    assert count(factory, Incident) == count(factory, AuditLog) == 1
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("header", ["Origin", "X-CSRF-Token"])
@pytest.mark.parametrize("missing", [False, True])
def test_escalation_requires_origin_and_csrf(escalation, header, missing):
    # Arrange
    client, factory, _, identifier, *_ = escalation
    if missing:
        client.headers.pop(header)
    else:
        client.headers[header] = "invalid"
    # Act
    response = escalate(client, identifier)
    # Assert
    assert response.status_code == 403 and count(factory, Incident) == count(factory, AuditLog) == 0


@pytest.mark.parametrize("payload", [{"severity": "CRITICAL"}, {"status": "RESOLVED"}, {"analyst_id": str(uuid4())}, [], "private-input"])
def test_client_cannot_supply_incident_fields(escalation, payload):
    # Arrange
    client, factory, _, identifier, *_ = escalation
    # Act
    response = client.post(f"/investigations/{identifier}/escalate", json=payload)
    # Assert
    assert response.status_code == 422 and response.json() == {"detail": "Requisição inválida."}
    assert "private-input" not in response.text and count(factory, Incident) == 0


def test_empty_body_is_accepted(escalation):
    # Arrange
    client, _, _, identifier, *_ = escalation
    # Act
    response = client.post(f"/investigations/{identifier}/escalate", json={})
    # Assert
    assert response.status_code == 201


@pytest.mark.parametrize("method,path,expected", [
    ("get", "/incidents/private-id", 422),
    ("post", "/investigations/private-id/escalate", 422),
    ("get", "/incidents/" + str(uuid4()), 404),
])
def test_invalid_or_missing_incident_reference(escalation, method, path, expected):
    # Arrange
    client, factory, *_ = escalation
    # Act
    response = client.request(method, path)
    # Assert
    assert response.status_code == expected and "private-id" not in response.text
    assert count(factory, Incident) == count(factory, AuditLog) == 0


@pytest.mark.parametrize("failure", ["incident", "audit", "database_audit", "commit"])
def test_failures_revert_all_writes(escalation, failure, monkeypatch, caplog):
    # Arrange
    client, factory, alert_id, identifier, *_ = escalation
    before = evidence(factory)
    original = client.get(f"/investigations/{identifier}").json()
    def fail(*args, **kwargs):
        raise RuntimeError("private-failure-value")
    def fail_audit(db, **values):
        db.flush()
        fail()
    append = service.append_audit
    def invalid_audit(db, **values):
        values["author_id"] = uuid4()
        append(db, **values)
    if failure == "audit":
        monkeypatch.setattr(service, "append_audit", fail_audit)
    elif failure == "database_audit":
        monkeypatch.setattr(service, "append_audit", invalid_audit)
    callback = "before_commit" if failure == "commit" else "before_flush"
    if failure in {"incident", "commit"}:
        event.listen(factory.class_, callback, fail)
    # Act
    try:
        response = escalate(client, identifier)
    finally:
        if failure in {"incident", "commit"}:
            event.remove(factory.class_, callback, fail)
    # Assert
    assert response.status_code == 500 and "private-failure-value" not in response.text + caplog.text
    assert count(factory, Incident) == count(factory, AuditLog) == 0
    assert client.get(f"/investigations/{identifier}").json() == original
    assert evidence(factory) == before
    with factory() as db:
        assert db.get(AlertRecord, alert_id).status == "IN_REVIEW"


def test_database_rejects_duplicate_incident(escalation):
    # Arrange
    client, factory, alert_id, identifier, analyst_id, *_ = escalation
    escalate(client, identifier)
    # Act
    with pytest.raises(IntegrityError), factory.begin() as db:
        db.add(Incident(alert_id=alert_id, analyst_id=analyst_id, severity="HIGH",
                        status=IncidentStatus.OPEN, opened_at=datetime.now(timezone.utc)))
    # Assert
    assert count(factory, Incident) == count(factory, AuditLog) == 1


@pytest.mark.parametrize("changes", [
    {"alert_id": uuid4()}, {"analyst_id": uuid4()}, {"severity": "INVALID"}, {"status": "INVALID"},
])
def test_database_rejects_invalid_incident(escalation, changes):
    # Arrange
    _, factory, alert_id, _, analyst_id, *_ = escalation
    values = dict(id=uuid4(), alert_id=alert_id, analyst_id=analyst_id,
                  severity="HIGH", status="OPEN", opened_at=datetime.now(timezone.utc)) | changes
    # Act
    with pytest.raises(IntegrityError), factory.begin() as db:
        db.execute(text("INSERT INTO incidents (id, alert_id, analyst_id, severity, status, opened_at) "
                        "VALUES (:id, :alert_id, :analyst_id, :severity, :status, :opened_at)"), values)
    # Assert
    assert count(factory, Incident) == count(factory, AuditLog) == 0


def test_session_close_reverts_unconfirmed_escalation(escalation):
    # Arrange
    _, factory, alert_id, identifier, analyst_id, *_ = escalation
    # Act
    with factory() as db:
        service.escalate(db, analyst_id, UUID(identifier))
    # Assert
    assert count(factory, Incident) == count(factory, AuditLog) == 0
    with factory() as db:
        assert db.get(AlertRecord, alert_id).status == "IN_REVIEW"


def test_secrets_are_not_exposed(escalation, caplog):
    # Arrange
    client, factory, _, identifier, analyst_id, _, password, _ = escalation
    token = client.cookies.get(COOKIE_NAME)
    with factory() as db:
        encoded = db.get(User, analyst_id).password_hash
    # Act
    response = escalate(client, identifier)
    recovered = client.get("/incidents/" + response.json()["id"])
    # Assert
    for value in [password, token, encoded]:
        assert value not in response.text + recovered.text + caplog.text
    assert "password_hash" not in response.text + recovered.text


@pytest.mark.parametrize("method", ["patch", "delete", "post"])
def test_no_incident_treatment_routes(escalation, method):
    # Arrange
    client, factory, _, identifier, *_ = escalation
    created = escalate(client, identifier)
    # Act
    response = client.request(method, "/incidents/" + created.json()["id"], json={"status": "RESOLVED"})
    # Assert
    assert response.status_code == 405 and count(factory, AuditLog) == 1
    assert client.get("/incidents/" + created.json()["id"]).json()["status"] == "OPEN"
