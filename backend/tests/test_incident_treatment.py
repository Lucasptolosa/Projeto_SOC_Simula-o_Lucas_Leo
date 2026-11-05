from datetime import datetime, timezone
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError

from app.audit.models import AuditLog
from app.auth.models import AuthSession
from app.auth.service import COOKIE_NAME
from app.detection.models import AlertRecord
from app.incidents import service
from app.incidents.models import Incident
from app.incidents.schemas import TransitionInput
from app.incidents.transitions import IncidentStatus, IncidentTransitionError
from app.investigations.models import Observation
from app.investigations.service import InvestigationServiceError
from app.users.models import User
from test_incident_escalation import escalation, escalate
from test_investigations import investigation_context, count, evidence, login, with_instants
from test_logs import log_context


@pytest.fixture
def treatment(escalation):
    client, factory, alert_id, investigation_id, analyst_id, admin_id, password, connection = escalation
    response = escalate(client, investigation_id)
    assert response.status_code == 201
    return client, factory, UUID(response.json()["id"]), analyst_id, password, alert_id, investigation_id


def change(client, identifier, target, **fields):
    return client.post(f"/incidents/{identifier}/transitions", json={"target_status": target, **fields})


def details(target):
    if target == "CONTAINED":
        return {"containment_description": "  Isolamento ç\n"}
    if target == "RESOLVED":
        return {"resolution_conclusion": "  Correção e\u0301 verificada\n"}
    return {}


@pytest.mark.parametrize("contained", [False, True])
def test_lifecycle_preserves_authorship_history_and_text(treatment, contained):
    # Arrange
    client, factory, identifier, opener, password, alert_id, investigation_id = treatment
    original = client.get(f"/incidents/{identifier}").json()
    before = evidence(factory)
    client.post(f"/investigations/{investigation_id}/observations", json={"content": "histórico preservado"})
    observations = client.get(f"/investigations/{investigation_id}/observations").json()
    with factory.begin() as db:
        actor = User(username="incident-handler", role="ANALYST", password_hash=db.get(User, opener).password_hash)
        db.add(actor)
        db.flush()
        handler = actor.id
    login(client, "incident-handler", password)
    targets = ["UNDER_INVESTIGATION", *(["CONTAINED"] if contained else []), "RESOLVED"]
    earliest = datetime.now(timezone.utc)
    # Act
    responses = [change(client, identifier, target, **details(target)) for target in targets]
    recovered = client.get(f"/incidents/{identifier}")
    # Assert
    assert all(response.status_code == 200 for response in responses)
    body = recovered.json()
    assert with_instants(body) == with_instants(responses[-1].json())
    assert body["analyst_id"] == str(opener) and body["opened_at"] == original["opened_at"]
    assert body["severity"] == original["severity"] and body["alert_id"] == str(alert_id)
    assert body["status"] == "RESOLVED" and body["resolved_by"] == str(handler)
    assert body["resolution_conclusion"] == details("RESOLVED")["resolution_conclusion"]
    with factory() as db:
        incident = db.get(Incident, identifier)
        assert earliest <= incident.resolved_at <= datetime.now(timezone.utc)
        assert db.get(AlertRecord, alert_id).status == "ESCALATED"
        audits = db.scalars(select(AuditLog).where(AuditLog.entity_type == "INCIDENT").order_by(AuditLog.occurred_at)).all()
        assert [(a.old_status, a.new_status) for a in audits] == list(zip(["OPEN", *targets[:-1]], targets))
        assert all(a.author_id == handler and a.entity_id == str(identifier) and
                   a.action == "INCIDENT_STATUS_CHANGED" and a.old_role is a.new_role is None for a in audits)
        assert audits[-1].occurred_at == incident.resolved_at
        if contained:
            assert incident.containment_description == details("CONTAINED")["containment_description"]
            assert incident.contained_by == handler and incident.contained_at == audits[-2].occurred_at
        else:
            assert incident.containment_description is incident.contained_by is incident.contained_at is None
    assert count(factory, AuditLog) == len(targets) + 1 and count(factory, Observation) == 1
    assert client.get(f"/investigations/{investigation_id}/observations").json() == observations
    assert evidence(factory) == before and recovered.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("current", list(IncidentStatus))
@pytest.mark.parametrize("target", list(IncidentStatus))
def test_transition_matrix_uses_current_persistent_state(treatment, current, target):
    # Arrange
    client, factory, identifier, *_ = treatment
    with factory.begin() as db:
        db.get(Incident, identifier).status = current
    before = client.get(f"/incidents/{identifier}").json()
    allowed = (current, target) in {
        ("OPEN", "UNDER_INVESTIGATION"), ("UNDER_INVESTIGATION", "CONTAINED"),
        ("UNDER_INVESTIGATION", "RESOLVED"), ("CONTAINED", "RESOLVED"),
    }
    # Act
    response = change(client, identifier, target, **details(target))
    # Assert
    assert response.status_code == (200 if allowed else 409)
    assert count(factory, AuditLog) == (2 if allowed else 1)
    if not allowed:
        assert client.get(f"/incidents/{identifier}").json() == before


@pytest.mark.parametrize("target,field", [("CONTAINED", "containment_description"), ("RESOLVED", "resolution_conclusion")])
@pytest.mark.parametrize("value", [None, "", " \t\n\u2003", "bad\x00text", "\ud800", 12, True, [], {}])
def test_invalid_text_is_rejected_without_exposure(treatment, target, field, value, caplog):
    # Arrange
    client, factory, identifier, *_ = treatment
    change(client, identifier, "UNDER_INVESTIGATION")
    before = client.get(f"/incidents/{identifier}").json()
    payload = json.dumps({"target_status": target, field: value})
    # Act
    response = client.post(f"/incidents/{identifier}/transitions", content=payload,
                           headers={"Content-Type": "application/json"})
    # Assert
    assert response.status_code == 422 and response.json() == {"detail": "Requisição inválida."}
    assert client.get(f"/incidents/{identifier}").json() == before and count(factory, AuditLog) == 2
    assert "bad" not in response.text + caplog.text


@pytest.mark.parametrize("payload", [
    {}, {"target_status": "contained"}, {"target_status": None}, {"target_status": 1},
    {"target_status": "CONTAINED"}, {"target_status": "RESOLVED"},
    {"target_status": "UNDER_INVESTIGATION", "containment_description": "unexpected"},
    {"target_status": "UNDER_INVESTIGATION", "resolution_conclusion": None},
    {"target_status": "CONTAINED", "containment_description": "valid", "resolution_conclusion": "unexpected"},
    {"target_status": "RESOLVED", "resolution_conclusion": "valid", "containment_description": None},
    {"target_status": "UNDER_INVESTIGATION", "analyst_id": str(uuid4())},
    {"target_status": "UNDER_INVESTIGATION", "opened_at": "2026-01-01T00:00:00Z"},
    [], None, "private-input",
])
def test_payload_requires_exact_transition_fields(treatment, payload):
    # Arrange
    client, factory, identifier, *_ = treatment
    # Act
    response = client.post(f"/incidents/{identifier}/transitions", json=payload)
    # Assert
    assert response.status_code == 422 and "private-input" not in response.text
    assert count(factory, AuditLog) == 1
    assert client.get(f"/incidents/{identifier}").json()["status"] == "OPEN"


@pytest.mark.parametrize("value", ["\u00e9", "  e\u0301\t\n", "🙂" * 30000], ids=["minimal", "preserved", "long"])
def test_valid_text_has_no_truncation_or_normalization(treatment, value):
    # Arrange
    client, _, identifier, *_ = treatment
    change(client, identifier, "UNDER_INVESTIGATION")
    # Act
    response = change(client, identifier, "RESOLVED", resolution_conclusion=value)
    # Assert
    assert response.status_code == 200 and response.json()["resolution_conclusion"] == value
    assert client.get(f"/incidents/{identifier}").json()["resolution_conclusion"] == value


@pytest.mark.parametrize("actor,expected", [("admin", 403), ("anonymous", 401), ("inactive", 401), ("revoked", 401)])
def test_transition_requires_active_analyst(treatment, actor, expected):
    # Arrange
    client, factory, identifier, author, password, *_ = treatment
    if actor == "admin":
        login(client, "log-admin", password)
    elif actor == "anonymous":
        client.cookies.clear()
    else:
        with factory.begin() as db:
            if actor == "inactive":
                db.get(User, author).status = "INACTIVE"
            else:
                for session in db.scalars(select(AuthSession)):
                    session.revoked_at = datetime.now(timezone.utc)
    # Act
    response = change(client, identifier, "UNDER_INVESTIGATION")
    # Assert
    assert response.status_code == expected and count(factory, AuditLog) == 1
    assert response.headers["cache-control"] == "no-store"
    with factory() as db:
        assert db.get(Incident, identifier).status is IncidentStatus.OPEN


@pytest.mark.parametrize("header", ["Origin", "X-CSRF-Token"])
@pytest.mark.parametrize("missing", [False, True])
def test_transition_requires_origin_and_csrf(treatment, header, missing):
    # Arrange
    client, factory, identifier, *_ = treatment
    if missing:
        client.headers.pop(header)
    else:
        client.headers[header] = "invalid"
    # Act
    response = change(client, identifier, "UNDER_INVESTIGATION")
    # Assert
    assert response.status_code == 403 and count(factory, AuditLog) == 1


@pytest.mark.parametrize("identifier,expected", [(str(uuid4()), 404), ("private-id", 422)])
def test_missing_or_invalid_incident(treatment, identifier, expected):
    # Arrange
    client, factory, *_ = treatment
    # Act
    response = change(client, identifier, "UNDER_INVESTIGATION")
    # Assert
    assert response.status_code == expected and "private-id" not in response.text
    assert count(factory, AuditLog) == 1


@pytest.mark.parametrize("target", ["CONTAINED", "RESOLVED"])
@pytest.mark.parametrize("failure", ["flush", "audit", "database_audit", "commit"])
def test_treatment_failures_revert_incident_and_audit(treatment, target, failure, monkeypatch, caplog):
    # Arrange
    client, factory, identifier, *_ = treatment
    change(client, identifier, "UNDER_INVESTIGATION")
    before = client.get(f"/incidents/{identifier}").json()
    def fail(*args, **kwargs):
        raise RuntimeError("private-failure-value")
    original = service.append_audit
    def audit_failure(db, **values):
        db.flush()
        fail()
    def invalid_audit(db, **values):
        values["author_id"] = uuid4()
        original(db, **values)
    if failure == "audit":
        monkeypatch.setattr(service, "append_audit", audit_failure)
    elif failure == "database_audit":
        monkeypatch.setattr(service, "append_audit", invalid_audit)
    callback = "before_commit" if failure == "commit" else "before_flush"
    if failure in {"flush", "commit"}:
        event.listen(factory.class_, callback, fail)
    # Act
    try:
        response = change(client, identifier, target, **details(target))
    finally:
        if failure in {"flush", "commit"}:
            event.remove(factory.class_, callback, fail)
    # Assert
    assert response.status_code == 500 and "private-failure-value" not in response.text + caplog.text
    assert client.get(f"/incidents/{identifier}").json() == before and count(factory, AuditLog) == 2


def test_session_close_rolls_back_unconfirmed_treatment(treatment):
    # Arrange
    _, factory, identifier, author, *_ = treatment
    # Act
    with factory() as db:
        service.transition(db, author, identifier, TransitionInput(target_status="UNDER_INVESTIGATION"))
    # Assert
    with factory() as db:
        assert db.get(Incident, identifier).status is IncidentStatus.OPEN
    assert count(factory, AuditLog) == 1


@pytest.mark.parametrize("change_kind", ["status", "role", "inactive"])
def test_service_refreshes_cached_state_and_identity(treatment, change_kind):
    # Arrange
    _, factory, identifier, author, *_ = treatment
    with factory() as db:
        cached_incident, cached_author = db.get(Incident, identifier), db.get(User, author)
        with factory.begin() as other:
            if change_kind == "status":
                other.get(Incident, identifier).status = "RESOLVED"
            elif change_kind == "role":
                other.get(User, author).role = "ADMIN"
            else:
                other.get(User, author).status = "INACTIVE"
        # Act
        with pytest.raises(IncidentTransitionError if change_kind == "status" else InvestigationServiceError):
            service.transition(db, author, identifier, TransitionInput(target_status="UNDER_INVESTIGATION"))
        # Assert
        assert cached_incident is not None and cached_author is not None
    assert count(factory, AuditLog) == 1


@pytest.mark.parametrize("field", ["containment_description", "contained_by", "contained_at",
                                 "resolution_conclusion", "resolved_by", "resolved_at"])
def test_database_rejects_partial_treatment_metadata(treatment, field):
    # Arrange
    _, factory, identifier, author, *_ = treatment
    value = author if field.endswith("_by") else datetime.now(timezone.utc) if field.endswith("_at") else "text"
    # Act
    with pytest.raises(IntegrityError), factory.begin() as db:
        setattr(db.get(Incident, identifier), field, value)
    # Assert
    assert count(factory, AuditLog) == 1


@pytest.mark.parametrize("prefix", ["contained", "resolved"])
def test_database_preserves_treatment_author_reference(treatment, prefix):
    # Arrange
    _, factory, identifier, *_ = treatment
    text_field = "containment_description" if prefix == "contained" else "resolution_conclusion"
    # Act
    with pytest.raises(IntegrityError), factory.begin() as db:
        row = db.get(Incident, identifier)
        setattr(row, text_field, "preserved")
        setattr(row, prefix + "_by", uuid4())
        setattr(row, prefix + "_at", datetime.now(timezone.utc))
    # Assert
    assert count(factory, AuditLog) == 1


def test_treatment_does_not_expose_secrets(treatment, caplog):
    # Arrange
    client, factory, identifier, author, password, *_ = treatment
    token = client.cookies.get(COOKIE_NAME)
    with factory() as db:
        encoded = db.get(User, author).password_hash
    # Act
    response = change(client, identifier, "UNDER_INVESTIGATION")
    recovered = client.get(f"/incidents/{identifier}")
    # Assert
    assert response.status_code == recovered.status_code == 200
    assert all(secret not in response.text + recovered.text + caplog.text for secret in [token, password, encoded])
    assert "password_hash" not in response.text + recovered.text
