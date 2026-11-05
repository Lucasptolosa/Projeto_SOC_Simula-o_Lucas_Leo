from datetime import datetime, timedelta, timezone
from hashlib import sha256
from uuid import UUID, uuid4

from pydantic import ValidationError
import pytest
from sqlalchemy import event, select

from app.assets.models import Asset
from app.audit.models import AuditLog
from app.auth.models import AuthSession
from app.auth.service import COOKIE_NAME
from app.db.base import Base
from app.detection.models import AlertLog, AlertRecord
from app.detection_engine import DetectionEngine
from app.incidents import service
from app.incidents.models import Incident
from app.incidents.schemas import IncidentsQuery, PublicIncident
from app.incidents.transitions import IncidentStatus
from app.investigations.models import Investigation, Observation
from app.investigations.service import InvestigationServiceError
from app.logs.models import LogRecord
from app.users.models import User
from test_investigations import login, with_instants
from test_logs import log_context


START = datetime(2026, 11, 6, 12, tzinfo=timezone.utc)
PRIORITY_IDS = [2, 3, 4, 5, 6, 8, 7, 10, 11, 1, 9, 12]
DATA = [
    (9, "RESOLVED", "LOW", 0, 0), (8, "OPEN", "HIGH", 2, 1),
    (4, "UNDER_INVESTIGATION", "CRITICAL", 1, 0), (3, "CONTAINED", "CRITICAL", 0, 1),
    (2, "OPEN", "CRITICAL", 0, 0), (7, "RESOLVED", "MEDIUM", -1, 0),
    (6, "CONTAINED", "HIGH", 1, 0), (5, "UNDER_INVESTIGATION", "HIGH", 0, 1),
    (1, "OPEN", "LOW", -5, 0), (10, "UNDER_INVESTIGATION", "MEDIUM", 0, 1),
    (11, "CONTAINED", "MEDIUM", 0, 0), (12, "RESOLVED", "LOW", 1, 1),
]


@pytest.fixture
def incident_queries(log_context):
    client, factory, asset, _, analyst, password, connection = log_context
    with factory.begin() as db:
        inactive = Asset(name="inactive", type="APPLICATION", status="INACTIVE")
        db.add(inactive)
        db.flush()
        assets = [asset, inactive.id]
        for number, status, severity, hours, asset_number in DATA:
            instant = START + timedelta(hours=hours)
            event_id, alert_id = f"incident-{number}", uuid4()
            db.add(LogRecord(event_id=event_id, asset_id=assets[asset_number],
                             occurred_at=START - timedelta(days=2), event_type="AUTH_FAILURE", username="monitored"))
            db.flush()
            db.add(AlertRecord(id=alert_id, rule_id="DR01", asset_id=assets[asset_number], username="monitored",
                               trigger_event_id=event_id, severity=severity, status="ESCALATED", created_at=START - timedelta(days=1)))
            db.flush()
            investigation = Investigation(alert_id=alert_id, analyst_id=analyst, started_at=START - timedelta(days=1))
            db.add(investigation)
            db.flush()
            db.add_all([AlertLog(alert_id=alert_id, event_id=event_id, position=1),
                        Observation(investigation_id=investigation.id, analyst_id=analyst,
                                    content="preserved", occurred_at=instant)])
            values = {}
            if status == "CONTAINED":
                values.update(containment_description="isolated", contained_by=analyst, contained_at=instant)
            elif status == "RESOLVED":
                values.update(resolution_conclusion="resolved", resolved_by=analyst, resolved_at=instant)
            db.add(Incident(id=UUID(int=number), alert_id=alert_id, analyst_id=analyst,
                            status=status, severity=severity, opened_at=instant, **values))
        db.add(AuditLog(author_id=analyst, action="INCIDENT_STATUS_CHANGED", entity_type="INCIDENT",
                        entity_id=str(UUID(int=9)), old_status="UNDER_INVESTIGATION", new_status="RESOLVED", occurred_at=START))
    login(client, "log-analyst", password)
    return client, factory, assets, analyst, password, connection


def identifiers(response):
    return [UUID(row["id"]).int for row in response.json()["items"]]


def snapshot(factory):
    with factory() as db:
        return {table.name: sha256(repr(db.execute(select(table).order_by(*table.primary_key)).all()).encode()).hexdigest()
                for table in Base.metadata.sorted_tables}


def test_unfiltered_query_defaults_priority_and_persistence(incident_queries):
    # Arrange
    client, factory, _, analyst, *_ = incident_queries
    # Act
    response = client.get("/incidents")
    # Assert
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"items", "total", "page", "page_size"}
    assert (body["total"], body["page"], body["page_size"]) == (12, 1, 20)
    assert identifiers(response) == PRIORITY_IDS
    assert {row["status"] for row in body["items"]} == {status.value for status in IncidentStatus}
    assert {row["severity"] for row in body["items"]} == {"LOW", "MEDIUM", "HIGH", "CRITICAL"}
    with factory() as db:
        for actual in body["items"]:
            expected = PublicIncident.model_validate(db.get(Incident, UUID(actual["id"]))).model_dump(mode="json")
            assert with_instants(actual) == with_instants(expected)
            assert actual["analyst_id"] == str(analyst)
    assert response.headers["cache-control"] == "no-store" and response.headers["pragma"] == "no-cache"


def test_empty_query_uses_shared_page(log_context):
    # Arrange
    client, _, _, _, _, password, _ = log_context
    login(client, "log-analyst", password)
    # Act
    response = client.get("/incidents")
    # Assert
    assert response.status_code == 200 and response.json() == {"items": [], "total": 0, "page": 1, "page_size": 20}


@pytest.mark.parametrize("size", [1, 2, 5, 20, 100])
def test_pages_preserve_priority_and_do_not_repeat(incident_queries, size):
    # Arrange
    client, *_ = incident_queries
    pages = range(1, (len(DATA) + size - 1) // size + 2)
    # Act
    responses = [client.get("/incidents", params={"page": page, "page_size": size}) for page in pages]
    repeated = client.get("/incidents", params={"page": 1, "page_size": size})
    # Assert
    collected = [identifier for response in responses for identifier in identifiers(response)]
    assert all(response.status_code == 200 and response.json()["total"] == 12 for response in responses)
    assert collected == PRIORITY_IDS and len(set(collected)) == 12
    assert repeated.json() == responses[0].json() and responses[-1].json()["items"] == []


def test_highest_page_is_valid(incident_queries):
    # Arrange
    client, *_ = incident_queries
    # Act
    response = client.get("/incidents", params={"page": 10000, "page_size": 100})
    # Assert
    assert response.status_code == 200 and response.json() == {"items": [], "total": 12, "page": 10000, "page_size": 100}


@pytest.mark.parametrize("status", list(IncidentStatus))
def test_status_filter_uses_incident_status(incident_queries, status):
    # Arrange
    client, *_ = incident_queries
    expected = {number for number, value, *_ in DATA if value == status}
    # Act
    response = client.get("/incidents", params={"status": status})
    # Assert
    assert response.status_code == 200 and response.json()["total"] == 3
    assert identifiers(response) == [identifier for identifier in PRIORITY_IDS if identifier in expected]
    assert all(row["status"] == status for row in response.json()["items"])


@pytest.mark.parametrize("severity", ["LOW", "MEDIUM", "HIGH", "CRITICAL"])
def test_severity_filter_uses_incident_snapshot(incident_queries, severity):
    # Arrange
    client, factory, *_ = incident_queries
    expected = {number for number, _, value, *_ in DATA if value == severity}
    with factory.begin() as db:
        for alert in db.scalars(select(AlertRecord)):
            alert.severity = "LOW"
    # Act
    response = client.get("/incidents", params={"severity": severity})
    # Assert
    assert response.status_code == 200 and response.json()["total"] == 3
    assert identifiers(response) == [identifier for identifier in PRIORITY_IDS if identifier in expected]
    assert all(row["severity"] == severity for row in response.json()["items"])


@pytest.mark.parametrize("asset_number", [0, 1, 2])
def test_asset_filter_uses_existing_alert_relation(incident_queries, asset_number):
    # Arrange
    client, _, assets, *_ = incident_queries
    selected = assets[asset_number] if asset_number < 2 else uuid4()
    expected = {number for number, _, _, _, asset in DATA if asset == asset_number}
    # Act
    response = client.get("/incidents", params={"asset_id": str(selected)})
    # Assert
    assert response.status_code == 200 and response.json()["total"] == len(expected)
    assert identifiers(response) == [identifier for identifier in PRIORITY_IDS if identifier in expected]


@pytest.mark.parametrize("params,expected", [
    ({"opened_from": START.isoformat()}, [2, 3, 4, 5, 6, 8, 10, 11, 9, 12]),
    ({"opened_to": START.isoformat()}, [2, 3, 5, 7, 10, 11, 1, 9]),
    ({"opened_from": START.isoformat(), "opened_to": START.isoformat()}, [2, 3, 5, 10, 11, 9]),
    ({"opened_from": "2026-11-06T09:00:00-03:00", "opened_to": "2026-11-06T13:00:00Z"}, [2, 3, 4, 5, 6, 10, 11, 9, 12]),
    ({"opened_from": "2026-11-07T00:00:00Z"}, []),
    ({"opened_to": "2026-11-05T00:00:00Z"}, []),
    ({"opened_from": "2026-11-06T09:00:00-03:00", "opened_to": "2026-11-06T12:00:00+00:00"}, [2, 3, 5, 10, 11, 9]),
], ids=["lower", "upper", "equal", "both", "after", "before", "offsets"])
def test_opening_interval_is_inclusive(incident_queries, params, expected):
    # Arrange
    client, *_ = incident_queries
    # Act
    response = client.get("/incidents", params=params)
    # Assert
    assert response.status_code == 200 and identifiers(response) == expected
    assert response.json()["total"] == len(expected)


def test_all_filters_apply_before_count_and_pagination(incident_queries):
    # Arrange
    client, _, assets, *_ = incident_queries
    params = dict(status="UNDER_INVESTIGATION", severity="HIGH", asset_id=str(assets[1]),
                  opened_from=START.isoformat(), opened_to=START.isoformat(), page_size=1)
    # Act
    response = client.get("/incidents", params=params)
    following = client.get("/incidents", params=params | {"page": 2})
    mismatched = client.get("/incidents", params=params | {"asset_id": str(assets[0])})
    # Assert
    assert response.status_code == 200 and identifiers(response) == [5] and response.json()["total"] == 1
    assert following.json() == {"items": [], "total": 1, "page": 2, "page_size": 1}
    assert mismatched.json() == {"items": [], "total": 0, "page": 1, "page_size": 1}


@pytest.mark.parametrize("params", [
    {"page": 0}, {"page": -1}, {"page": 10001}, {"page": "1.5"}, {"page": "invalid"},
    {"page_size": 0}, {"page_size": 101}, {"page_size": -1}, {"page_size": "invalid"},
    {"status": "NEW"}, {"status": "open"}, {"status": ""}, {"severity": "critical"}, {"severity": "INVALID"},
    {"asset_id": "private-value"}, {"sort": "severity"}, {"opened_at": START.isoformat()},
    {"opened_from": "2026-11-06"}, {"opened_to": "2026-11-06T12:00:00"}, {"opened_from": "invalid"},
    {"opened_to": "1793966400"}, {"opened_from": "2026-11-06T12:00:00+25:00"},
    {"opened_from": "2026-11-06T13:00:00Z", "opened_to": START.isoformat()},
], ids=["page_zero", "page_negative", "page_max", "page_fraction", "page_text", "size_zero", "size_max", "size_negative", "size_text",
        "status_alert", "status_case", "status_empty", "severity_case", "severity_unknown", "asset", "sort", "unknown_date",
        "date_only", "date_naive", "date_text", "date_number", "date_offset", "inverted"])
def test_invalid_query_is_safe_and_preserves_data(incident_queries, params, caplog):
    # Arrange
    client, factory, *_ = incident_queries
    before = snapshot(factory)
    # Act
    response = client.get("/incidents", params=params)
    # Assert
    assert response.status_code == 422 and response.json() == {"detail": "Requisição inválida."}
    assert response.headers["cache-control"] == "no-store" and snapshot(factory) == before
    assert "private-value" not in response.text + caplog.text


@pytest.mark.parametrize("actor,expected", [("admin", 403), ("anonymous", 401), ("inactive", 401), ("revoked", 401)])
def test_query_requires_active_analyst(incident_queries, actor, expected):
    # Arrange
    client, factory, _, analyst, password, _ = incident_queries
    if actor == "admin":
        login(client, "log-admin", password)
    elif actor == "anonymous":
        client.cookies.clear()
    else:
        with factory.begin() as db:
            if actor == "inactive":
                db.get(User, analyst).status = "INACTIVE"
            else:
                for session in db.scalars(select(AuthSession)):
                    session.revoked_at = START - timedelta(days=1)
    # Act
    response = client.get("/incidents")
    # Assert
    assert response.status_code == expected and "items" not in response.json()
    assert response.headers["cache-control"] == "no-store"


def test_query_is_read_only_and_does_not_require_write_headers(incident_queries, monkeypatch, caplog):
    # Arrange
    client, factory, _, analyst, password, connection = incident_queries
    token = client.cookies.get(COOKIE_NAME)
    with factory() as db:
        encoded = db.get(User, analyst).password_hash
    before = snapshot(factory)
    def reject_audit(*args, **kwargs):
        raise AssertionError("Consulta não deve auditar.")
    def reject_writes(conn, cursor, statement, parameters, context, many):
        assert statement.split()[0].upper() not in {"INSERT", "UPDATE", "DELETE"}
        assert "FOR UPDATE" not in statement.upper()
    monkeypatch.setattr(service, "append_audit", reject_audit)
    monkeypatch.setattr(DetectionEngine, "process_batch", reject_audit)
    client.headers.pop("Origin")
    client.headers.pop("X-CSRF-Token")
    event.listen(connection, "before_cursor_execute", reject_writes)
    # Act
    try:
        response = client.get("/incidents", params={"page_size": 2})
        recovered = client.get("/incidents/" + response.json()["items"][0]["id"])
    finally:
        event.remove(connection, "before_cursor_execute", reject_writes)
    # Assert
    assert response.status_code == recovered.status_code == 200 and snapshot(factory) == before
    assert with_instants(response.json()["items"][0]) == with_instants(recovered.json())
    assert all(secret not in response.text + caplog.text for secret in [token, password, encoded])
    assert all(field not in response.text for field in ["password_hash", "token_hash", "payload"])


@pytest.mark.parametrize("state", ["ADMIN", "INACTIVE"])
def test_service_revalidates_cached_author(incident_queries, state):
    # Arrange
    _, factory, _, analyst, *_ = incident_queries
    with factory() as db:
        cached = db.get(User, analyst)
        with factory.begin() as other:
            actor = other.get(User, analyst)
            if state == "ADMIN":
                actor.role = state
            else:
                actor.status = state
        # Act
        with pytest.raises(InvestigationServiceError):
            service.list_incidents(db, analyst, IncidentsQuery())
        # Assert
        assert cached.role.value == "ADMIN" if state == "ADMIN" else cached.status.value == "INACTIVE"


@pytest.mark.parametrize("value", [123, True, []])
def test_schema_rejects_non_iso_temporal_values(value):
    # Arrange
    params = {"opened_from": value}
    # Act
    with pytest.raises(ValidationError):
        IncidentsQuery(**params)
    # Assert
    assert params == {"opened_from": value}
