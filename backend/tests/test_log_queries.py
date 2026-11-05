from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import event, select, update

from app.assets.models import Asset
from app.db.base import Base
from app.detection import service as detection
from app.logs import repository, service
from app.logs.models import LogRecord
from app.logs.schemas import LogsQuery
from app.users.models import User, UserStatus
from test_detection_persistence import record
from test_investigations import login
from test_logs import log_context


START = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)


@pytest.fixture
def query_context(log_context):
    client, factory, asset_id, admin, analyst, password, connection = log_context
    with factory.begin() as db:
        second = Asset(name="inactive", type="APPLICATION", status="INACTIVE")
        db.add(second)
        db.flush()
        second_id = second.id
        values = [
            (1, asset_id, "AUTH_FAILURE", "Alice", 0),
            (2, asset_id, "AUTH_SUCCESS", "alice", 0),
            (3, asset_id, "ADMIN_ACCESS", " Alice ", 60),
            (4, second_id, "AUTH_FAILURE", "Alice", 120),
            (5, asset_id, "AUTH_FAILURE", "Alice", 180),
            (6, asset_id, "AUTH_SUCCESS", "Alice", 180),
            (7, second_id, "AUTH_FAILURE", "Alice", 180),
            (8, asset_id, "AUTH_FAILURE", "Alice", 240),
        ]
        db.add_all([LogRecord(event_id=f"q-{number:03d}", asset_id=asset,
            event_type=kind, username=username, occurred_at=START+timedelta(seconds=seconds))
            for number, asset, kind, username, seconds in values])
    return client, factory, asset_id, second_id, admin, analyst, password, connection


def numbers(body):
    return [int(item["event_id"].split("-")[1]) for item in body["items"]]


def fingerprint(factory):
    with factory() as db:
        return {table.name: sha256(json.dumps([list(row) for row in
            db.execute(select(table).order_by(*table.primary_key.columns))],
            default=str).encode()).hexdigest() for table in Base.metadata.sorted_tables}


@pytest.mark.parametrize("role", ["admin", "analyst"])
def test_both_roles_can_read_without_write_headers(query_context, role):
    # Arrange
    client, _, _, _, _, _, password, _ = query_context
    if role == "analyst": login(client, "log-analyst", password)
    del client.headers["Origin"]
    del client.headers["X-CSRF-Token"]
    # Act
    response = client.get("/logs")
    # Assert
    assert response.status_code == 200
    assert response.json()["total"] == 8
    assert (response.json()["page"], response.json()["page_size"]) == (1, 20)
    assert numbers(response.json()) == [8, 5, 6, 7, 4, 3, 1, 2]
    assert set(response.json()["items"][0]) == {"event_id", "asset_id", "event_type", "username", "occurred_at"}
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("field,value,expected", [
    ("event_type", "AUTH_FAILURE", [8, 5, 7, 4, 1]),
    ("event_type", "AUTH_SUCCESS", [6, 2]), ("event_type", "ADMIN_ACCESS", [3]),
    ("username", "Alice", [8, 5, 6, 7, 4, 1]), ("username", "alice", [2]),
    ("username", " Alice ", [3]), ("username", "ALICE", []),
    ("username", "Ali%", []), ("username", "' OR 1=1 --", []),
])
def test_individual_filters_use_exact_values(query_context, field, value, expected):
    # Arrange
    client, *_ = query_context
    # Act
    response = client.get("/logs", params={field: value})
    # Assert
    assert response.status_code == 200
    assert numbers(response.json()) == expected
    assert response.json()["total"] == len(expected)


def test_all_filters_are_applied_together(query_context):
    # Arrange
    client, _, asset, *_ = query_context
    params = dict(asset_id=str(asset), event_type="AUTH_FAILURE", username="Alice",
                  occurred_from="2026-11-03T09:03:00-03:00", occurred_to="2026-11-03T12:03:00Z")
    # Act
    response = client.get("/logs", params=params)
    # Assert
    assert response.status_code == 200 and numbers(response.json()) == [5]
    assert response.json()["total"] == 1


@pytest.mark.parametrize("params,expected", [
    ({"occurred_from": "2026-11-03T12:03:00Z"}, [8, 5, 6, 7]),
    ({"occurred_to": "2026-11-03T09:01:00-03:00"}, [3, 1, 2]),
    ({"occurred_from": "2026-11-03T12:01:00Z", "occurred_to": "2026-11-03T12:02:00Z"}, [4, 3]),
])
def test_period_limits_are_inclusive_and_independent(query_context, params, expected):
    # Arrange
    client, *_ = query_context
    # Act
    response = client.get("/logs", params=params)
    # Assert
    assert response.status_code == 200 and numbers(response.json()) == expected


def test_inactive_asset_keeps_history_visible(query_context):
    # Arrange
    client, _, _, asset, *_ = query_context
    # Act
    response = client.get("/logs", params={"asset_id": str(asset)})
    # Assert
    assert response.status_code == 200
    assert numbers(response.json()) == [7, 4]


@pytest.mark.parametrize("params", [{"asset_id": str(uuid4())}, {"username": "absent"}, {"page": 10000}])
def test_valid_query_without_results_is_empty(query_context, params):
    # Arrange
    client, *_ = query_context
    # Act
    response = client.get("/logs", params=params)
    # Assert
    assert response.status_code == 200 and response.json()["items"] == []
    assert response.json()["total"] == (8 if "page" in params else 0)


def test_pagination_preserves_order_and_total(query_context):
    # Arrange
    client, *_ = query_context
    # Act
    first = client.get("/logs", params={"page_size": 2}).json()
    second = client.get("/logs", params={"page": 2, "page_size": 2}).json()
    largest = client.get("/logs", params={"page_size": 100}).json()
    # Assert
    assert numbers(first) == [8, 5] and numbers(second) == [6, 7]
    assert first["total"] == second["total"] == largest["total"] == 8
    assert len(largest["items"]) == 8


@pytest.mark.parametrize("params", [
    {"page": 0}, {"page": 10001}, {"page_size": 0}, {"page_size": 101}, {"page": "x"},
    {"page_size": "1.5"}, {"asset_id": "invalid"}, {"event_type": "auth_failure"},
    {"event_type": "OTHER"}, {"username": ""}, {"username": " \t"}, {"username": "\x00"},
    {"occurred_from": "123"}, {"occurred_to": "invalid"},
    {"occurred_from": "2026-11-03T12:00:00"}, {"occurred_to": "2026-11-03T12:00:00"},
    {"occurred_from": "2026-11-03T12:01:00Z", "occurred_to": "2026-11-03T12:00:00Z"},
    {"occurred_from": "2026-11-03T12:00:00-03:00", "occurred_to": "2026-11-03T12:00:00Z"},
    {"extra": "private-marker"},
])
def test_invalid_parameters_preserve_data_and_hide_input(query_context, params):
    # Arrange
    client, factory, *_ = query_context
    before = fingerprint(factory)
    # Act
    response = client.get("/logs", params=params)
    # Assert
    assert response.status_code == 422 and response.json() == {"detail": "Requisição inválida."}
    assert "private-marker" not in response.text
    assert fingerprint(factory) == before


@pytest.mark.parametrize("role", ["admin", "analyst"])
@pytest.mark.parametrize("mode", ["anonymous", "inactive", "revoked"])
def test_invalid_identity_is_denied(query_context, role, mode):
    # Arrange
    client, factory, _, _, admin, analyst, password, _ = query_context
    actor = admin if role == "admin" else analyst
    if role == "analyst": login(client, "log-analyst", password)
    if mode == "anonymous": client.cookies.clear()
    elif mode == "revoked": assert client.post("/auth/logout").status_code == 204
    else:
        with factory.begin() as db: db.get(User, actor).status = "INACTIVE"
    # Act
    response = client.get("/logs")
    # Assert
    assert response.status_code == 401


def test_read_does_not_write_commit_or_evaluate_motor(log_context, monkeypatch):
    # Arrange
    client, factory, asset, _, _, _, connection = log_context
    assert client.post("/logs/import", json=[record(asset, n, n) for n in range(5)]).json()["detection"]["alerts_created"] == 1
    before = fingerprint(factory)
    verbs = []
    def observe(conn, cursor, statement, parameters, context, executemany):
        verb = statement.lstrip().split(None, 1)[0].upper()
        if verb in {"INSERT", "UPDATE", "DELETE"}: verbs.append(verb)
    def fail(*args, **kwargs): raise AssertionError("Leitura não deve alterar registros.")
    # Act
    event.listen(connection, "before_cursor_execute", observe)
    try:
        with monkeypatch.context() as patch:
            patch.setattr(factory.class_, "commit", fail)
            patch.setattr(detection, "evaluate", fail)
            patch.setattr(detection, "lock_state", fail)
            response = client.get("/logs")
    finally:
        event.remove(connection, "before_cursor_execute", observe)
    # Assert
    assert response.status_code == 200 and response.json()["total"] == 5
    assert verbs == [] and fingerprint(factory) == before


@pytest.mark.parametrize("actor,reason", [("missing", "inactive_author"), ("inactive", "inactive_author"), ("unknown_role", "forbidden_author")])
def test_service_revalidates_identity(query_context, monkeypatch, actor, reason):
    # Arrange
    _, factory, _, _, admin, *_ = query_context
    target = uuid4() if actor == "missing" else admin
    if actor == "inactive":
        with factory.begin() as db: db.get(User, admin).status = "INACTIVE"
    elif actor == "unknown_role":
        monkeypatch.setattr(service.user_repository, "current_user", lambda *a, **kw: SimpleNamespace(status=UserStatus.ACTIVE, role="OTHER"))
    # Act
    with factory() as db, pytest.raises(service.LogQueryError) as error:
        service.list_logs(db, target, LogsQuery())
    # Assert
    assert str(error.value) == reason


def test_cached_author_cannot_read_after_deactivation(query_context):
    # Arrange
    _, factory, _, _, admin, *_, connection = query_context
    with factory() as db:
        cached = db.get(User, admin)
        connection.execute(update(User).where(User.id == admin).values(status="INACTIVE"))
        # Act
        with pytest.raises(service.LogQueryError) as error:
            service.list_logs(db, admin, LogsQuery())
        # Assert
        assert str(error.value) == "inactive_author" and cached.status.value == "INACTIVE"


@pytest.mark.parametrize("reason,expected", [("inactive_author", 401), ("forbidden_author", 403)])
def test_service_errors_are_mapped_to_http(query_context, monkeypatch, reason, expected):
    # Arrange
    client, *_ = query_context
    def fail(*args, **kwargs): raise service.LogQueryError(reason)
    monkeypatch.setattr(service, "list_logs", fail)
    # Act
    response = client.get("/logs")
    # Assert
    assert response.status_code == expected


def test_unexpected_error_has_no_private_values_or_mutations(query_context, monkeypatch, caplog):
    # Arrange
    client, factory, *_ = query_context
    before = fingerprint(factory)
    def fail(*args, **kwargs): raise RuntimeError("private-marker")
    monkeypatch.setattr(repository, "list_logs", fail)
    client.raise_server_exceptions = False
    # Act
    response = client.get("/logs")
    # Assert
    assert response.status_code == 500 and "private-marker" not in response.text + caplog.text
    assert fingerprint(factory) == before


def test_empty_database_is_a_valid_query(log_context):
    # Arrange
    client, *_ = log_context
    # Act
    response = client.get("/logs")
    # Assert
    assert response.status_code == 200
    assert response.json() == dict(items=[], total=0, page=1, page_size=20)


@pytest.mark.parametrize("params", [{"occurred_from": 123}, {"occurred_to": True},
    {"username": "\ud800"}, {"username": 1}, {"occurred_from": datetime(2026, 11, 3)}])
def test_query_schema_rejects_invalid_internal_types(params):
    # Arrange
    invalid = params
    # Act
    with pytest.raises(ValidationError) as error:
        LogsQuery(**invalid)
    # Assert
    assert error.value.error_count() >= 1


def test_query_schema_accepts_explicit_optional_none():
    # Arrange
    params = dict(username=None, occurred_from=None, occurred_to=None)
    # Act
    result = LogsQuery(**params)
    # Assert
    assert result.username is result.occurred_from is result.occurred_to is None
