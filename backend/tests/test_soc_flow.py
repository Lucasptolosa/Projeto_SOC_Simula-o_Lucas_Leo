from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import json
from pathlib import Path
import secrets
import subprocess
import sys
from threading import Barrier
from uuid import UUID

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import event, func, select, text

from app.audit.models import AuditLog
from app.auth.dependencies import get_auth_settings
from app.auth.service import COOKIE_NAME
from app.core.passwords import hash_password
from app.db.session import create_session_factory, get_session
from app.detection.models import AlertLog, AlertRecord, DetectionState
from app.incidents.models import Incident
from app.investigations.models import Investigation, Observation
from app.logs.models import LogRecord
from app.main import app
from app.users.models import User
from test_detection_persistence import record
from test_detection_transactions import committed_detection_db
from test_investigations import login
from test_logs import ORIGIN


@pytest.fixture
def flow(committed_detection_db, test_db_settings):
    engine, schema, admins, _ = committed_detection_db
    password = secrets.token_urlsafe(24)
    factory = create_session_factory(engine)
    def session():
        db = factory()
        assert db.scalar(text("SELECT current_database()")) == "mini_soc_test"
        db.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        return db
    with session() as db:
        encoded = hash_password(password)
        db.get(User, admins[0]).password_hash = encoded
        analyst = User(username="flow-analyst", role="ANALYST", password_hash=encoded)
        other = User(username="flow-other", role="ANALYST", password_hash=encoded)
        db.add_all([analyst, other])
        db.flush()
        author = analyst.id
        db.commit()
    previous = app.dependency_overrides.copy()
    def database():
        with session() as db:
            yield db
    settings = test_db_settings.model_copy(update={"auth_origin": ORIGIN, "auth_cookie_secure": True})
    app.dependency_overrides[get_session] = database
    app.dependency_overrides[get_auth_settings] = lambda: settings
    try:
        with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as client:
            login(client, "admin-0", password)
            response = client.post("/assets", json={"name": "flow-owned", "type": "SERVER", "status": "ACTIVE"})
            assert response.status_code == 201
            yield client, session, factory, UUID(response.json()["id"]), author, password, schema
    finally:
        app.dependency_overrides.clear()
        app.dependency_overrides.update(previous)


def begin_investigation(flow):
    client, session, _, asset, _, password, _ = flow
    response = client.post("/logs/import", json=[record(asset, n, n) for n in range(5)])
    assert response.status_code == 200 and response.json()["detection"]["alerts_created"] == 1
    with session() as db:
        alert = db.scalar(select(AlertRecord).where(AlertRecord.asset_id == asset))
        assert alert.status == "NEW" and alert.severity == "HIGH"
        alert_id = alert.id
    login(client, "flow-analyst", password)
    response = client.post("/investigations", json={"alert_id": str(alert_id)})
    assert response.status_code == 201
    return UUID(response.json()["id"]), alert_id


def audit_rows(session):
    with session() as db:
        return [(row.action, row.entity_id, row.old_status, row.new_status, row.author_id)
                for row in db.scalars(select(AuditLog).order_by(AuditLog.occurred_at, AuditLog.id))]


def test_full_flow_recovers_after_new_application_process(flow):
    # Arrange
    client, session, _, asset, author, password, schema = flow
    investigation, alert_id = begin_investigation(flow)
    with session() as db:
        original_logs = db.execute(select(LogRecord.event_id, LogRecord.occurred_at).order_by(LogRecord.event_id)).all()
        original_evidence = db.execute(select(AlertLog).order_by(AlertLog.position)).scalars().all()
        evidence_ids = [(row.alert_id, row.event_id, row.position) for row in original_evidence]
    # Act
    observed = client.post(f"/investigations/{investigation}/observations", json={"content": "Evidence verified"})
    escalated = client.post(f"/investigations/{investigation}/escalate")
    assert observed.status_code == escalated.status_code == 201
    identifier = escalated.json()["id"]
    transitions = [
        {"target_status": "UNDER_INVESTIGATION"},
        {"target_status": "CONTAINED", "containment_description": "  Isolated\n"},
        {"target_status": "RESOLVED", "resolution_conclusion": "  Recovery verified\n"},
    ]
    responses = [client.post(f"/incidents/{identifier}/transitions", json=payload) for payload in transitions]
    recovered = client.get(f"/incidents/{identifier}")
    child = r'''
import json,sys
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.core.config import Settings
from app.db.session import create_db_engine,create_session_factory,get_session
from app.auth.dependencies import get_auth_settings
from app.auth.service import COOKIE_NAME
from app.main import app
data=json.load(sys.stdin)
assert data['schema'].startswith('test_detection_') and len(data['schema'])==47
settings=Settings(_env_file=Path('.env.test'))
assert settings.db_name=='mini_soc_test'
engine=create_db_engine(settings);factory=create_session_factory(engine)
def database():
    with factory() as db:
        assert db.scalar(text('SELECT current_database()'))=='mini_soc_test'
        db.execute(text('SET LOCAL search_path TO "'+data['schema']+'"'))
        yield db
app.dependency_overrides[get_session]=database
app.dependency_overrides[get_auth_settings]=lambda:settings.model_copy(update={'auth_origin':'https://testserver','auth_cookie_secure':True})
with TestClient(app,base_url='https://testserver') as client:
    client.cookies.set(COOKIE_NAME,data['token'])
    response=client.get('/incidents/'+data['id'])
    print(json.dumps({'http_status':response.status_code,'incident':response.json()}))
engine.dispose()
'''
    restarted = subprocess.run([sys.executable, "-c", child],
        input=json.dumps({"schema": schema, "id": identifier, "token": client.cookies.get(COOKIE_NAME)}),
        text=True, capture_output=True, timeout=30, cwd=Path(__file__).resolve().parents[1],
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    page = client.get("/incidents", params={"asset_id": str(asset), "status": "RESOLVED"})
    login(client, "admin-0", password)
    audit_response = client.get("/audit-logs")
    # Assert
    assert all(response.status_code == 200 for response in responses)
    body = recovered.json()
    assert recovered.status_code == 200 and body["status"] == "RESOLVED" and body["severity"] == "HIGH"
    assert body["containment_description"] == "  Isolated\n" and body["resolution_conclusion"] == "  Recovery verified\n"
    assert body["analyst_id"] == body["contained_by"] == body["resolved_by"] == str(author)
    assert page.json()["total"] == 1 and page.json()["items"][0]["id"] == identifier
    assert restarted.returncode == 0
    child_result = json.loads(restarted.stdout)
    assert child_result["http_status"] == 200 and child_result["incident"]["status"] == "RESOLVED"
    assert child_result["incident"]["opened_at"] == body["opened_at"]
    with session() as db:
        assert db.execute(select(LogRecord.event_id, LogRecord.occurred_at).order_by(LogRecord.event_id)).all() == original_logs
        assert [(row.alert_id, row.event_id, row.position) for row in db.scalars(select(AlertLog).order_by(AlertLog.position))] == evidence_ids
        assert db.get(AlertRecord, alert_id).status == "ESCALATED"
        assert db.scalar(select(Observation.content)) == "Evidence verified"
    audits = audit_rows(session)
    assert [row[0] for row in audits] == ["ASSET_CREATED", "ALERT_ESCALATED", *(["INCIDENT_STATUS_CHANGED"] * 3)]
    assert audits[1][1:4] == (str(alert_id), "IN_REVIEW", "ESCALATED")
    assert all(row[4] == author for row in audits[1:])
    assert all(row[1] == identifier for row in audits[2:])
    assert [(row[2], row[3]) for row in audits[2:]] == [("OPEN", "UNDER_INVESTIGATION"), ("UNDER_INVESTIGATION", "CONTAINED"), ("CONTAINED", "RESOLVED")]
    assert audit_response.status_code == 200 and audit_response.json()["total"] == 5


def test_false_positive_flow_preserves_evidence_without_incident(flow):
    # Arrange
    client, session, *_ = flow
    identifier, alert = begin_investigation(flow)
    # Act
    observed = client.post(f"/investigations/{identifier}/observations", json={"content": "Legitimate operation"})
    dismissed = client.post(f"/investigations/{identifier}/false-positive", json={"justification": "Authorized test"})
    denied = client.post(f"/investigations/{identifier}/escalate")
    # Assert
    assert observed.status_code == 201 and dismissed.status_code == 200 and denied.status_code == 409
    with session() as db:
        assert db.scalar(select(func.count()).select_from(Incident)) == 0
        assert db.get(AlertRecord, alert).status == "DISMISSED"
        assert db.get(Investigation, identifier).justification == "Authorized test"
        assert db.scalar(select(func.count()).select_from(LogRecord)) == 5
        assert db.scalar(select(func.count()).select_from(AlertLog)) == 5
    assert [row[0] for row in audit_rows(session)] == ["ASSET_CREATED", "ALERT_DISMISSED"]


def test_mixed_import_duplicate_and_out_of_order_preserve_confirmed_data(flow):
    # Arrange
    client, session, _, asset, *_ = flow
    records = [record(asset, n, n) for n in range(5)]
    # Act
    mixed = client.post("/logs/import", json=[*records, {"event_id": "invalid"}, records[0]])
    duplicate = client.post("/logs/import", json=records)
    old = client.post("/logs/import", json=[record(asset, 100, -1)])
    # Assert
    assert mixed.status_code == duplicate.status_code == old.status_code == 200
    assert (mixed.json()["accepted"], mixed.json()["rejected"], mixed.json()["detection"]["alerts_created"]) == (5, 2, 1)
    assert duplicate.json()["accepted"] == duplicate.json()["detection"]["alerts_created"] == 0
    assert duplicate.json()["rejected"] == 5
    assert old.json()["accepted"] == 1 and old.json()["detection"]["rejected"] == 1
    with session() as db:
        assert db.scalar(select(func.count()).select_from(LogRecord)) == 6
        assert db.scalar(select(func.count()).select_from(AlertRecord)) == 1
        assert db.scalar(select(func.count()).select_from(AlertLog)) == 5


def test_authorization_revocation_and_invalid_transition_preserve_state(flow):
    # Arrange
    client, session, _, asset, _, password, _ = flow
    identifier, _ = begin_investigation(flow)
    incident = client.post(f"/investigations/{identifier}/escalate").json()["id"]
    # Act
    import_denied = client.post("/logs/import", json=[record(asset, 100, 100)])
    invalid = client.post(f"/incidents/{incident}/transitions", json={"target_status": "RESOLVED", "resolution_conclusion": "not permitted"})
    logout = client.post("/auth/logout")
    revoked = client.get(f"/incidents/{incident}")
    login(client, "admin-0", password)
    role_denied = client.get(f"/incidents/{incident}")
    # Assert
    assert (import_denied.status_code, invalid.status_code, logout.status_code, revoked.status_code, role_denied.status_code) == (403, 409, 204, 401, 403)
    with session() as db:
        assert db.get(Incident, UUID(incident)).status.value == "OPEN"
        assert db.scalar(select(func.count()).select_from(LogRecord)) == 5
    assert [row[0] for row in audit_rows(session)] == ["ASSET_CREATED", "ALERT_ESCALATED"]


@pytest.mark.parametrize("operation", ["import", "escalate"])
def test_commit_failure_rolls_back_pipeline_and_can_retry(flow, operation):
    # Arrange
    client, session, factory, asset, *_ = flow
    identifier = begin_investigation(flow)[0] if operation == "escalate" else None
    with session() as db: before = deepcopy(db.get(DetectionState, 1).payload)
    def fail(db): raise RuntimeError("Synthetic commit failure")
    event.listen(factory.class_, "before_commit", fail)
    path = f"/investigations/{identifier}/escalate" if identifier else "/logs/import"
    payload = None if identifier else [record(asset, n, n) for n in range(5)]
    # Act
    try:
        response = client.post(path) if identifier else client.post(path, json=payload)
    finally:
        event.remove(factory.class_, "before_commit", fail)
    # Assert
    assert response.status_code == 500
    with session() as db:
        assert db.scalar(select(func.count()).select_from(Incident)) == 0
        assert db.get(DetectionState, 1).payload == before
        assert db.scalar(select(func.count()).select_from(LogRecord)) == (5 if identifier else 0)
        if identifier: assert db.scalar(select(AlertRecord.status)) == "IN_REVIEW"
    assert len(audit_rows(session)) == 1
    retry = client.post(path) if identifier else client.post(path, json=payload)
    assert retry.status_code == (201 if identifier else 200)


def test_concurrent_http_escalations_commit_one_incident(flow):
    # Arrange
    client, session, _, _, _, password, _ = flow
    identifier, alert = begin_investigation(flow)
    barrier = Barrier(2)
    def compete(browser):
        barrier.wait(timeout=5)
        return browser.post(f"/investigations/{identifier}/escalate").status_code
    with TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN}) as other:
        login(other, "flow-other", password)
        # Act
        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(compete, browser) for browser in (client, other)]
            statuses = [future.result(timeout=20) for future in futures]
    # Assert
    assert sorted(statuses) == [201, 409]
    with session() as db:
        assert db.scalar(select(func.count()).select_from(Incident)) == 1
        assert db.get(AlertRecord, alert).status == "ESCALATED"
    assert [row[0] for row in audit_rows(session)] == ["ASSET_CREATED", "ALERT_ESCALATED"]
