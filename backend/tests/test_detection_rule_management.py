from copy import deepcopy
from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import delete, event, func, select, update

from app.audit.models import AuditLog
from app.detection import service
from app.detection.models import AlertLog, AlertRecord, DetectionRuleRecord, DetectionState
from app.detection.schemas import UpdateRuleInput
from app.users.models import User
from test_detection_persistence import record
from test_logs import log_context


def audit_count(factory):
    with factory() as db:
        return db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.entity_type == "DETECTION_RULE"))


@pytest.mark.parametrize("rule,severity", [("DR01", "HIGH"), ("DR02", "MEDIUM"), ("DR03", "MEDIUM")])
def test_deactivation_and_activation_persist_with_single_audit(log_context, rule, severity):
    # Arrange
    client, factory, _, admin_id, *_ = log_context
    before = datetime.now(timezone.utc)
    # Act
    inactive = client.patch(f"/detection-rules/{rule}", json={"status": "INACTIVE"})
    active = client.patch(f"/detection-rules/{rule}", json={"status": "ACTIVE"})
    # Assert
    assert inactive.status_code == active.status_code == 200
    assert inactive.json() == dict(id=rule, status="INACTIVE", severity=severity)
    assert active.json() == dict(id=rule, status="ACTIVE", severity=severity)
    assert inactive.headers["cache-control"] == "no-store"
    with factory() as db:
        assert db.get(DetectionRuleRecord, rule).status == "ACTIVE"
        audits = db.scalars(select(AuditLog).where(AuditLog.entity_type == "DETECTION_RULE").order_by(AuditLog.occurred_at)).all()
        assert [item.action for item in audits] == ["DETECTION_RULE_DEACTIVATED", "DETECTION_RULE_ACTIVATED"]
        assert all(item.author_id == admin_id and item.entity_id == rule for item in audits)
        assert all(before <= item.occurred_at <= datetime.now(timezone.utc) for item in audits)
        assert all(item.old_role is None and item.new_role is None for item in audits)


@pytest.mark.parametrize("status", ["ACTIVE", "INACTIVE"])
def test_repetition_does_not_create_audit_or_change_state(log_context, status):
    # Arrange
    client, factory, *_ = log_context
    if status == "INACTIVE":
        assert client.patch("/detection-rules/DR01", json={"status": status}).status_code == 200
    before = audit_count(factory)
    with factory() as db:
        snapshot = deepcopy(db.get(DetectionState, 1).payload)
    # Act
    response = client.patch("/detection-rules/DR01", json={"status": status})
    # Assert
    assert response.status_code == 200
    assert audit_count(factory) == before
    with factory() as db:
        assert db.get(DetectionState, 1).payload == snapshot


@pytest.mark.parametrize("body", [{}, {"status": None}, {"status": True}, {"status": 1},
    {"status": "active"}, {"status": " ACTIVE "}, {"status": "OTHER"},
    {"status": "INACTIVE", "severity": "LOW"}, {"status": "INACTIVE", "id": "DR02"},
    {"status": "INACTIVE", "extra": "private-marker"}, [], "INACTIVE"])
def test_invalid_payload_preserves_status_and_audit(log_context, body):
    # Arrange
    client, factory, *_ = log_context
    # Act
    response = client.patch("/detection-rules/DR01", json=body)
    # Assert
    assert response.status_code == 422
    assert response.json() == {"detail": "Requisição inválida."}
    assert "private-marker" not in response.text
    assert audit_count(factory) == 0
    with factory() as db:
        assert db.get(DetectionRuleRecord, "DR01").status == "ACTIVE"


@pytest.mark.parametrize("rule", ["DR04", "dr01", "unknown"])
def test_unknown_rule_is_not_created(log_context, rule):
    # Arrange
    client, factory, *_ = log_context
    # Act
    response = client.patch(f"/detection-rules/{rule}", json={"status": "INACTIVE"})
    # Assert
    assert response.status_code == 404
    assert audit_count(factory) == 0
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(DetectionRuleRecord)) == 3


@pytest.mark.parametrize("mode,status", [("anonymous", 401), ("analyst", 403), ("inactive", 401),
    ("revoked", 401), ("origin", 403), ("csrf", 403)])
def test_authorization_and_session_protections(log_context, mode, status):
    # Arrange
    client, factory, _, admin_id, _, password, _ = log_context
    if mode == "anonymous":
        client.cookies.clear()
    elif mode == "analyst":
        login = client.post("/auth/login", json={"username": "log-analyst", "password": password})
        client.headers["X-CSRF-Token"] = login.json()["csrf_token"]
    elif mode == "inactive":
        with factory.begin() as db:
            db.get(User, admin_id).status = "INACTIVE"
    elif mode == "revoked":
        assert client.post("/auth/logout").status_code == 204
    elif mode == "origin":
        client.headers["Origin"] = "https://other.invalid"
    elif mode == "csrf":
        del client.headers["X-CSRF-Token"]
    # Act
    response = client.patch("/detection-rules/DR01", json={"status": "INACTIVE"})
    # Assert
    assert response.status_code == status
    assert audit_count(factory) == 0
    with factory() as db:
        assert db.get(DetectionRuleRecord, "DR01").status == "ACTIVE"


@pytest.mark.parametrize("actor,reason", [("missing", "inactive_author"), ("inactive", "inactive_author"), ("analyst", "forbidden_author")])
def test_service_revalidates_author(log_context, actor, reason):
    # Arrange
    _, factory, _, admin_id, analyst_id, *_ = log_context
    target = uuid4() if actor == "missing" else analyst_id if actor == "analyst" else admin_id
    if actor == "inactive":
        with factory.begin() as db:
            db.get(User, admin_id).status = "INACTIVE"
    # Act
    with factory() as db, pytest.raises(service.DetectionRuleError) as error:
        service.update_rule_status(db, target, "DR01", "INACTIVE")
    # Assert
    assert str(error.value) == reason
    assert audit_count(factory) == 0


def test_cached_author_cannot_keep_old_role(log_context):
    # Arrange
    _, factory, _, admin_id, *_, connection = log_context
    with factory() as db:
        cached = db.get(User, admin_id)
        assert cached.role.value == "ADMIN"
        connection.execute(update(User).where(User.id == admin_id).values(role="ANALYST"))
        # Act
        with pytest.raises(service.DetectionRuleError) as error:
            service.update_rule_status(db, admin_id, "DR01", "INACTIVE")
        # Assert
        assert str(error.value) == "forbidden_author"
        assert cached.role.value == "ANALYST"
    assert audit_count(factory) == 0


@pytest.mark.parametrize("phase", ["audit", "constraint", "commit"])
def test_failure_rolls_back_rule_and_audit(log_context, monkeypatch, phase, caplog):
    # Arrange
    client, factory, *_ = log_context
    original = service.append_audit
    def fail(*args, **kwargs):
        raise RuntimeError("private-marker")
    def invalid_audit(db, **kwargs):
        original(db, **(kwargs | {"author_id": uuid4()}))
    if phase == "audit":
        monkeypatch.setattr(service, "append_audit", fail)
    elif phase == "constraint":
        monkeypatch.setattr(service, "append_audit", invalid_audit)
    else:
        event.listen(factory.class_, "before_commit", fail)
    client.raise_server_exceptions = False
    # Act
    try:
        response = client.patch("/detection-rules/DR01", json={"status": "INACTIVE"})
    finally:
        if phase == "commit":
            event.remove(factory.class_, "before_commit", fail)
    # Assert
    assert response.status_code == 500
    assert "private-marker" not in response.text + caplog.text
    assert audit_count(factory) == 0
    with factory() as db:
        assert db.get(DetectionRuleRecord, "DR01").status == "ACTIVE"


def test_api_status_controls_next_batches_and_preserves_history(log_context):
    # Arrange
    client, factory, asset_id, *_ = log_context
    assert client.post("/logs/import", json=[record(asset_id, n, n) for n in range(5)]).json()["detection"]["alerts_created"] == 1
    with factory() as db:
        previous = db.scalars(select(AlertRecord)).one()
        original = (previous.id, previous.severity, previous.status, previous.created_at)
        evidence = db.scalars(select(AlertLog.event_id).order_by(AlertLog.position)).all()
    # Act
    inactive = client.patch("/detection-rules/DR01", json={"status": "INACTIVE"})
    disabled = client.post("/logs/import", json=[record(asset_id, n, 200+n) for n in range(5, 10)])
    active = client.patch("/detection-rules/DR01", json={"status": "ACTIVE"})
    enabled = client.post("/logs/import", json=[record(asset_id, 10, 211)])
    # Assert
    assert inactive.status_code == active.status_code == 200
    assert disabled.json()["detection"]["alerts_created"] == 0
    assert enabled.json()["detection"]["alerts_created"] == 1
    with factory() as db:
        previous = db.get(AlertRecord, original[0])
        assert (previous.id, previous.severity, previous.status, previous.created_at) == original
        assert db.scalars(select(AlertLog.event_id).where(AlertLog.alert_id == previous.id).order_by(AlertLog.position)).all() == evidence


@pytest.mark.parametrize("missing", ["rule", "state"])
def test_missing_rule_or_state_never_reinitializes_catalog(log_context, missing):
    # Arrange
    client, factory, *_ = log_context
    with factory.begin() as db:
        db.execute(delete(DetectionRuleRecord).where(DetectionRuleRecord.id == "DR01") if missing == "rule" else delete(DetectionState))
    client.raise_server_exceptions = False
    # Act
    response = client.patch("/detection-rules/DR01", json={"status": "INACTIVE"})
    # Assert
    assert response.status_code == (404 if missing == "rule" else 500)
    assert audit_count(factory) == 0


def test_direct_service_rejects_invalid_status(log_context):
    # Arrange
    _, factory, _, author, *_ = log_context
    # Act
    with factory() as db, pytest.raises(ValidationError):
        service.update_rule_status(db, author, "DR01", "OTHER")
    # Assert
    assert audit_count(factory) == 0
