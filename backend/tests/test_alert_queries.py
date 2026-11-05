from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import event, select, update

from app.alerts import repository, service
from app.alerts.schemas import AlertsQuery
from app.assets.models import Asset
from app.db.base import Base
from app.detection.models import AlertLog, AlertRecord
from app.logs.models import LogRecord
from app.users.models import User
from test_investigations import login
from test_logs import log_context


START = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)


@pytest.fixture
def alerts_context(log_context):
    client, factory, asset_id, admin, analyst, password, connection = log_context
    with factory.begin() as db:
        second = Asset(name="historical", type="APPLICATION", status="INACTIVE")
        db.add(second)
        db.flush()
        second_id = second.id
        cases = [
            (1, "LOW", "NEW", "DR01", asset_id, 0),
            (2, "MEDIUM", "IN_REVIEW", "DR02", asset_id, 0),
            (3, "HIGH", "DISMISSED", "DR01", asset_id, 60),
            (4, "CRITICAL", "ESCALATED", "DR03", second_id, 120),
            (5, "HIGH", "NEW", "DR01", asset_id, 180),
            (6, "HIGH", "NEW", "DR02", asset_id, 180),
            (7, "HIGH", "NEW", "DR01", second_id, 180),
            (8, "HIGH", "NEW", "DR01", asset_id, 240),
        ]
        for number, severity, status, rule, asset, seconds in cases:
            instant = START + timedelta(seconds=seconds)
            ids = [f"e-{number}-z", f"e-{number}-a"]
            db.add_all([LogRecord(event_id=key, asset_id=asset,
                occurred_at=instant-timedelta(seconds=20-position),
                event_type="AUTH_FAILURE", username=" monitored ") for position, key in enumerate(ids)])
            db.flush()
            db.add(AlertRecord(id=UUID(int=number), rule_id=rule, asset_id=asset,
                username=" monitored ", trigger_event_id=ids[-1], severity=severity,
                status=status, created_at=instant))
            db.flush()
            db.add_all([AlertLog(alert_id=UUID(int=number), event_id=key, position=position)
                        for position, key in enumerate(ids, start=1)])
    login(client, "log-analyst", password)
    return client, factory, asset_id, second_id, admin, analyst, password, connection


def numbers(body):
    return [UUID(item["id"]).int for item in body["items"]]


def fingerprint(factory):
    with factory() as db:
        return {table.name: sha256(json.dumps([
            list(row) for row in db.execute(select(table).order_by(*table.primary_key.columns))
        ], default=str).encode()).hexdigest() for table in Base.metadata.sorted_tables}


def test_default_page_and_deterministic_order(alerts_context):
    # Arrange
    client, _, *_ = alerts_context
    # Act
    response = client.get("/alerts")
    # Assert
    assert response.status_code == 200
    assert response.json()["total"] == 8
    assert response.json()["page"] == 1 and response.json()["page_size"] == 20
    assert numbers(response.json()) == [8, 5, 6, 7, 4, 3, 1, 2]
    assert response.headers["cache-control"] == "no-store"
    assert set(response.json()["items"][0]) == {"id", "rule_id", "asset_id", "username", "severity", "status", "created_at"}


@pytest.mark.parametrize("field,value,expected", [
    ("severity", "LOW", [1]), ("severity", "MEDIUM", [2]),
    ("severity", "HIGH", [8, 5, 6, 7, 3]), ("severity", "CRITICAL", [4]),
    ("status", "NEW", [8, 5, 6, 7, 1]), ("status", "IN_REVIEW", [2]),
    ("status", "DISMISSED", [3]), ("status", "ESCALATED", [4]),
    ("rule_id", "DR01", [8, 5, 7, 3, 1]), ("rule_id", "DR02", [6, 2]),
    ("rule_id", "DR03", [4]),
])
def test_individual_enum_filters(alerts_context, field, value, expected):
    # Arrange
    client, *_ = alerts_context
    # Act
    response = client.get("/alerts", params={field: value})
    # Assert
    assert response.status_code == 200
    assert numbers(response.json()) == expected
    assert response.json()["total"] == len(expected)


def test_all_filters_are_intersected_including_equal_bounds(alerts_context):
    # Arrange
    client, _, asset, *_ = alerts_context
    params = dict(severity="HIGH", status="NEW", rule_id="DR01", asset_id=str(asset),
                  created_from="2026-11-03T09:03:00-03:00", created_to="2026-11-03T12:03:00Z")
    # Act
    response = client.get("/alerts", params=params)
    # Assert
    assert response.status_code == 200
    assert numbers(response.json()) == [5] and response.json()["total"] == 1


@pytest.mark.parametrize("params,expected", [
    ({"created_from": "2026-11-03T12:03:00Z"}, [8, 5, 6, 7]),
    ({"created_to": "2026-11-03T09:01:00-03:00"}, [3, 1, 2]),
    ({"created_from": "2026-11-03T12:01:00Z", "created_to": "2026-11-03T12:02:00Z"}, [4, 3]),
])
def test_period_limits_are_inclusive_and_independent(alerts_context, params, expected):
    # Arrange
    client, *_ = alerts_context
    # Act
    response = client.get("/alerts", params=params)
    # Assert
    assert response.status_code == 200
    assert numbers(response.json()) == expected


def test_asset_filter_includes_inactive_asset(alerts_context):
    # Arrange
    client, _, _, asset, *_ = alerts_context
    # Act
    response = client.get("/alerts", params={"asset_id": str(asset)})
    # Assert
    assert numbers(response.json()) == [7, 4]
    assert response.json()["total"] == 2


@pytest.mark.parametrize("params", [{"asset_id": str(uuid4())}, {"severity": "LOW", "status": "ESCALATED"}, {"page": 10000}])
def test_valid_query_without_matches_returns_empty_page(alerts_context, params):
    # Arrange
    client, *_ = alerts_context
    # Act
    response = client.get("/alerts", params=params)
    # Assert
    assert response.status_code == 200 and response.json()["items"] == []
    assert response.json()["total"] == (8 if "page" in params else 0)


def test_pages_have_no_overlap_with_equal_timestamps(alerts_context):
    # Arrange
    client, *_ = alerts_context
    # Act
    first = client.get("/alerts", params={"page_size": 2}).json()
    second = client.get("/alerts", params={"page": 2, "page_size": 2}).json()
    largest = client.get("/alerts", params={"page_size": 100}).json()
    # Assert
    assert numbers(first) == [8, 5] and numbers(second) == [6, 7]
    assert first["total"] == second["total"] == largest["total"] == 8
    assert len(largest["items"]) == 8


@pytest.mark.parametrize("params", [
    {"page": 0}, {"page": 10001}, {"page": "x"}, {"page_size": 0}, {"page_size": 101},
    {"page_size": "1.5"}, {"status": "OPEN"}, {"status": "new"}, {"severity": "critical"},
    {"severity": "EXTREME"}, {"rule_id": "DR04"}, {"rule_id": "dr01"}, {"asset_id": "invalid"},
    {"created_from": "2026-11-03T12:00:00"}, {"created_to": "2026-11-03T12:00:00"},
    {"created_from": "123"}, {"created_to": "junk"}, {"created_from": ""},
    {"created_from": "2026-11-03T12:01:00Z", "created_to": "2026-11-03T12:00:00Z"},
    {"created_from": "2026-11-03T12:00:00-03:00", "created_to": "2026-11-03T12:00:00Z"},
    {"extra": "private-marker"},
])
def test_invalid_filters_are_generic_and_do_not_modify_data(alerts_context, params):
    # Arrange
    client, factory, *_ = alerts_context
    before = fingerprint(factory)
    # Act
    response = client.get("/alerts", params=params)
    # Assert
    assert response.status_code == 422 and response.json() == {"detail": "Requisição inválida."}
    assert "private-marker" not in response.text
    assert fingerprint(factory) == before


def test_detail_preserves_original_evidence_order_and_values(alerts_context):
    # Arrange
    client, _, _, asset, *_ = alerts_context
    # Act
    response = client.get(f"/alerts/{UUID(int=4)}")
    # Assert
    assert response.status_code == 200
    result = response.json()
    assert result["severity"] == "CRITICAL" and result["status"] == "ESCALATED"
    assert UUID(result["asset_id"]) == asset and result["username"] == " monitored "
    assert [item["event_id"] for item in result["related_logs"]] == ["e-4-z", "e-4-a"]
    assert all(UUID(item["asset_id"]) == asset for item in result["related_logs"])
    assert all(item["username"] == " monitored " for item in result["related_logs"])
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("path,params,expected", [(str(uuid4()), {}, 404), ("invalid", {}, 422), (str(UUID(int=1)), {"extra": "private-marker"}, 422)])
def test_missing_invalid_or_extra_detail_input(alerts_context, path, params, expected):
    # Arrange
    client, factory, *_ = alerts_context
    before = fingerprint(factory)
    # Act
    response = client.get("/alerts/" + path, params=params)
    # Assert
    assert response.status_code == expected
    assert "private-marker" not in response.text
    assert fingerprint(factory) == before


@pytest.mark.parametrize("detail", [False, True])
@pytest.mark.parametrize("actor,expected", [("admin", 403), ("anonymous", 401), ("inactive", 401), ("revoked", 401), ("changed_role", 403)])
def test_read_permissions_are_enforced(alerts_context, detail, actor, expected):
    # Arrange
    client, factory, _, _, _, analyst, password, _ = alerts_context
    if actor == "admin":
        login(client, "log-admin", password)
    elif actor == "anonymous":
        client.cookies.clear()
    elif actor == "revoked":
        assert client.post("/auth/logout").status_code == 204
    else:
        with factory.begin() as db:
            user = db.get(User, analyst)
            if actor == "inactive": user.status = "INACTIVE"
            else: user.role = "ADMIN"
    # Act
    response = client.get(f"/alerts/{UUID(int=1)}" if detail else "/alerts")
    # Assert
    assert response.status_code == expected


def test_get_requires_session_but_not_write_headers(alerts_context):
    # Arrange
    client, *_ = alerts_context
    del client.headers["Origin"]
    del client.headers["X-CSRF-Token"]
    # Act
    listed = client.get("/alerts")
    detail = client.get(f"/alerts/{UUID(int=1)}")
    # Assert
    assert listed.status_code == detail.status_code == 200


def test_queries_never_commit_or_write_domain_data(alerts_context, monkeypatch):
    # Arrange
    client, factory, *_, connection = alerts_context
    before = fingerprint(factory)
    writes = []
    def observe(conn, cursor, statement, parameters, context, executemany):
        verb = statement.lstrip().split(None, 1)[0].upper()
        if verb in {"INSERT", "UPDATE", "DELETE"}: writes.append(verb)
    def fail(*args, **kwargs):
        raise AssertionError("Consulta não deve confirmar transação.")
    # Act
    event.listen(connection, "before_cursor_execute", observe)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(factory.class_, "commit", fail)
            listed = client.get("/alerts")
            detail = client.get(f"/alerts/{UUID(int=1)}")
    finally:
        event.remove(connection, "before_cursor_execute", observe)
    # Assert
    assert listed.status_code == detail.status_code == 200
    assert writes == [] and fingerprint(factory) == before


@pytest.mark.parametrize("detail", [False, True])
@pytest.mark.parametrize("actor,reason", [("missing", "inactive_author"), ("inactive", "inactive_author"), ("admin", "forbidden_author")])
def test_service_revalidates_author_before_read(alerts_context, detail, actor, reason):
    # Arrange
    _, factory, _, _, admin, analyst, *_ = alerts_context
    target = uuid4() if actor == "missing" else admin if actor == "admin" else analyst
    if actor == "inactive":
        with factory.begin() as db: db.get(User, analyst).status = "INACTIVE"
    # Act
    with factory() as db, pytest.raises(service.AlertQueryError) as error:
        if detail: service.get_alert(db, target, uuid4())
        else: service.list_alerts(db, target, AlertsQuery())
    # Assert
    assert str(error.value) == reason


def test_cached_identity_and_alert_cannot_return_old_values(alerts_context):
    # Arrange
    _, factory, _, _, _, analyst, _, connection = alerts_context
    with factory() as db:
        old_alert = db.get(AlertRecord, UUID(int=1))
        old_author = db.get(User, analyst)
        connection.execute(update(AlertRecord).where(AlertRecord.id == old_alert.id).values(status="IN_REVIEW"))
        # Act
        result = service.get_alert(db, analyst, old_alert.id)
        connection.execute(update(User).where(User.id == analyst).values(role="ADMIN"))
        with pytest.raises(service.AlertQueryError) as error:
            service.list_alerts(db, analyst, AlertsQuery())
        # Assert
        assert result["status"] == "IN_REVIEW"
        assert old_author.role.value == "ADMIN" and str(error.value) == "forbidden_author"


@pytest.mark.parametrize("operation", ["list_alerts", "evidence"])
def test_unexpected_query_error_is_generic_and_read_only(alerts_context, monkeypatch, caplog, operation):
    # Arrange
    client, factory, *_ = alerts_context
    before = fingerprint(factory)
    def fail(*args, **kwargs): raise RuntimeError("private-marker")
    monkeypatch.setattr(repository, operation, fail)
    client.raise_server_exceptions = False
    # Act
    response = client.get("/alerts" if operation == "list_alerts" else f"/alerts/{UUID(int=1)}")
    # Assert
    assert response.status_code == 500 and "private-marker" not in response.text + caplog.text
    assert fingerprint(factory) == before


@pytest.mark.parametrize("value", [123, True, "123", "2026-11-03T12:00:00", datetime(2026, 11, 3)])
def test_query_schema_requires_explicit_time_and_zone(value):
    # Arrange
    params = {"created_from": value}
    # Act
    with pytest.raises(ValidationError) as error:
        AlertsQuery(**params)
    # Assert
    assert error.value.error_count() >= 1


def test_empty_database_returns_empty_page(log_context):
    # Arrange
    client, _, _, _, _, password, _ = log_context
    login(client, "log-analyst", password)
    # Act
    response = client.get("/alerts")
    # Assert
    assert response.status_code == 200
    assert response.json() == dict(items=[], total=0, page=1, page_size=20)
