from copy import deepcopy
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import delete, event, func, select
from sqlalchemy.exc import IntegrityError

from app.detection import service as detection
from app.detection.models import AlertLog, AlertRecord, DetectionRuleRecord, DetectionState
from app.detection.state import dump_state, load_state
from app.detection_engine import DetectionEngine
from app.logs import service as ingestion
from app.logs.models import LogRecord
from test_logs import log_context, payload


START = datetime(2026, 11, 3, 12, tzinfo=timezone.utc)


def record(asset_id, number, seconds=0, **changes):
    return payload(asset_id, f"evt-{number:04d}",
                   occurred_at=(START + timedelta(seconds=seconds)).isoformat(), **changes)


def alerts(factory):
    with factory() as db:
        return db.scalars(select(AlertRecord).order_by(AlertRecord.created_at)).all()


def state_snapshot(factory):
    with factory() as db:
        return deepcopy(db.get(DetectionState, 1).payload)


@pytest.mark.parametrize("rule,kind,count,expected", [
    ("DR01", "AUTH_FAILURE", 4, 0), ("DR01", "AUTH_FAILURE", 5, 1),
    ("DR02", "AUTH_FAILURE", 2, 0), ("DR02", "AUTH_FAILURE", 3, 1),
    ("DR03", "ADMIN_ACCESS", 1, 1),
])
def test_import_generates_persisted_alert_and_evidence(log_context, rule, kind, count, expected):
    # Arrange
    client, factory, asset_id, *_ = log_context
    records = [record(asset_id, n, n, event_type=kind) for n in range(count)]
    if rule == "DR02":
        records.append(record(asset_id, 9, 10, event_type="AUTH_SUCCESS"))
    if rule == "DR03":
        records[0]["occurred_at"] = "2026-11-03T23:00:00Z"
    # Act
    response = client.post("/logs/import", json=list(reversed(records)))
    # Assert
    assert response.status_code == 200
    assert response.json()["detection"] == dict(evaluated=len(records), rejected=0, rejections=[], alerts_created=expected)
    saved = alerts(factory)
    assert len(saved) == expected
    if expected:
        alert = saved[0]
        assert isinstance(alert.id, UUID)
        assert (alert.rule_id, alert.status, alert.severity) == (rule, "NEW", "HIGH" if rule == "DR01" else "MEDIUM")
        assert alert.asset_id == asset_id and alert.username == "monitored-account"
        assert alert.created_at == datetime.fromisoformat(records[-1]["occurred_at"])
        with factory() as db:
            evidence = db.scalars(select(AlertLog.event_id).where(AlertLog.alert_id == alert.id).order_by(AlertLog.position)).all()
            assert evidence == [item["event_id"] for item in records]


@pytest.mark.parametrize("gap,expected", [(120, 1), (121, 0)])
def test_dr01_window_boundary_across_sessions(log_context, gap, expected):
    # Arrange
    client, factory, asset_id, *_ = log_context
    assert client.post("/logs/import", json=[record(asset_id, n, n) for n in range(4)]).status_code == 200
    # Act
    response = client.post("/logs/import", json=[record(asset_id, 4, gap)])
    # Assert
    assert response.json()["detection"]["alerts_created"] == expected
    assert len(alerts(factory)) == expected


def test_duplicate_and_continuing_sequence_never_emit_second_dr01(log_context):
    # Arrange
    client, factory, asset_id, *_ = log_context
    records = [record(asset_id, n, n) for n in range(5)]
    first = client.post("/logs/import", json=records)
    original_id = alerts(factory)[0].id
    # Act
    duplicate = client.post("/logs/import", json=records)
    continuing = client.post("/logs/import", json=[record(asset_id, n, n) for n in range(5, 10)])
    # Assert
    assert first.json()["detection"]["alerts_created"] == 1
    assert duplicate.json()["accepted"] == 0 and duplicate.json()["rejected"] == 5
    assert duplicate.json()["detection"]["evaluated"] == 0
    assert continuing.json()["detection"]["alerts_created"] == 0
    assert [alert.id for alert in alerts(factory)] == [original_id]


@pytest.mark.parametrize("offset", [-1, 0])
def test_out_of_order_persists_without_detection_or_state_change(log_context, offset):
    # Arrange
    client, factory, asset_id, *_ = log_context
    client.post("/logs/import", json=[record(asset_id, 1, 10)])
    before = state_snapshot(factory)
    old = record(asset_id, 2, 10 + offset, event_type="ADMIN_ACCESS")
    # Act
    response = client.post("/logs/import", json=[None, old])
    # Assert
    data = response.json()
    assert data["accepted"] == data["rejected"] == 1
    assert data["detection"] == dict(evaluated=0, rejected=1, alerts_created=0,
        rejections=[dict(position=2, reason="out_of_order", detail="Evento fora de ordem para detecção.")])
    assert state_snapshot(factory) == before
    with factory() as db:
        assert db.get(LogRecord, old["event_id"]) is not None
    assert alerts(factory) == []


def test_same_time_within_batch_uses_event_identifier_order(log_context):
    # Arrange
    client, factory, asset_id, *_ = log_context
    records = [record(asset_id, n) for n in range(5)]
    # Act
    response = client.post("/logs/import", json=list(reversed(records)))
    # Assert
    assert response.json()["detection"]["evaluated"] == 5
    assert alerts(factory)[0].trigger_event_id == records[-1]["event_id"]
    with factory() as db:
        assert db.scalars(select(AlertLog.event_id).order_by(AlertLog.position)).all() == [r["event_id"] for r in records]


def test_pair_isolation_and_dr02_success_consumption(log_context):
    # Arrange
    client, factory, asset_id, *_ = log_context
    failures = [record(asset_id, n, n) for n in range(3)]
    client.post("/logs/import", json=failures)
    # Act
    other = client.post("/logs/import", json=[record(asset_id, 8, 4, event_type="AUTH_SUCCESS", username="other")])
    success = client.post("/logs/import", json=[record(asset_id, 9, 5, event_type="AUTH_SUCCESS")])
    again = client.post("/logs/import", json=[record(asset_id, 10, 6, event_type="AUTH_SUCCESS")])
    # Assert
    assert other.json()["detection"]["alerts_created"] == 0
    assert success.json()["detection"]["alerts_created"] == 1
    assert again.json()["detection"]["alerts_created"] == 0
    assert [alert.rule_id for alert in alerts(factory)] == ["DR02"]


@pytest.mark.parametrize("gap,expected", [(300, 1), (301, 0)])
def test_dr02_lower_boundary_survives_new_service_instance(log_context, gap, expected):
    # Arrange
    client, factory, asset_id, *_ = log_context
    client.post("/logs/import", json=[record(asset_id, n, n) for n in range(3)])
    # Act
    response = client.post("/logs/import", json=[record(asset_id, 9, gap, event_type="AUTH_SUCCESS")])
    # Assert
    assert response.json()["detection"]["alerts_created"] == expected
    assert len(alerts(factory)) == expected


def test_inactive_rule_tracks_history_and_preserves_historical_alert(log_context):
    # Arrange
    client, factory, asset_id, *_ = log_context
    client.post("/logs/import", json=[record(asset_id, n, n) for n in range(5)])
    original = alerts(factory)[0]
    with factory.begin() as db:
        db.get(DetectionRuleRecord, "DR01").status = "INACTIVE"
    # Act
    response = client.post("/logs/import", json=[record(asset_id, n, 200 + n) for n in range(5, 10)])
    with factory.begin() as db:
        db.get(DetectionRuleRecord, "DR01").status = "ACTIVE"
    next_response = client.post("/logs/import", json=[record(asset_id, 10, 211)])
    # Assert
    assert response.json()["detection"]["alerts_created"] == 0
    assert next_response.json()["detection"]["alerts_created"] == 1
    saved = alerts(factory)
    assert len(saved) == 2
    assert (saved[0].id, saved[0].severity, saved[0].status) == (original.id, "HIGH", "NEW")


@pytest.mark.parametrize("phase", ["evaluation", "evidence", "commit"])
def test_failure_rolls_back_logs_alerts_and_state(log_context, monkeypatch, phase):
    # Arrange
    client, factory, asset_id, *_ = log_context
    before = state_snapshot(factory)
    records = [record(asset_id, n, n) for n in range(5)]
    def fail(*args, **kwargs):
        raise RuntimeError("synthetic failure")
    if phase == "evaluation":
        monkeypatch.setattr(detection, "dump_state", fail)
    elif phase == "evidence":
        event.listen(AlertLog, "before_insert", fail)
    else:
        event.listen(factory.class_, "before_commit", fail)
    client.raise_server_exceptions = False
    # Act
    try:
        response = client.post("/logs/import", json=records)
    finally:
        if phase == "evidence":
            event.remove(AlertLog, "before_insert", fail)
        if phase == "commit":
            event.remove(factory.class_, "before_commit", fail)
    # Assert
    assert response.status_code == 500
    assert "synthetic" not in response.text
    assert state_snapshot(factory) == before
    assert alerts(factory) == []
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(LogRecord)) == 0


@pytest.mark.parametrize("missing", ["state", "rule"])
def test_missing_catalog_or_state_fails_closed(log_context, missing):
    # Arrange
    client, factory, asset_id, *_ = log_context
    with factory.begin() as db:
        db.execute(delete(DetectionState) if missing == "state" else delete(DetectionRuleRecord).where(DetectionRuleRecord.id == "DR01"))
    client.raise_server_exceptions = False
    # Act
    response = client.post("/logs/import", json=[record(asset_id, 1)])
    # Assert
    assert response.status_code == 500
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(LogRecord)) == 0


def test_state_round_trip_preserves_sequences_and_counter():
    # Arrange
    engine = DetectionEngine()
    logs = [record("asset", n, n) for n in range(5)]
    engine.process_batch(logs)
    # Act
    snapshot = dump_state(engine)
    restored = load_state(snapshot)
    next_result = restored.process_batch([record("asset", 9, 9)])
    # Assert
    assert dump_state(load_state(snapshot)) == snapshot
    assert next_result.alerts == []
    assert len(next_result.accepted_logs) == 1


def test_unknown_snapshot_version_is_rejected():
    # Arrange
    snapshot = dump_state(DetectionEngine()) | {"version": 2}
    # Act
    with pytest.raises(ValueError) as error:
        load_state(snapshot)
    # Assert
    assert "Versão" in str(error.value)


def test_evidence_cannot_be_deleted(log_context):
    # Arrange
    client, factory, asset_id, *_ = log_context
    client.post("/logs/import", json=[record(asset_id, n, n) for n in range(5)])
    # Act
    with factory() as db, pytest.raises(IntegrityError):
        db.execute(delete(LogRecord).where(LogRecord.event_id == "evt-0000"))
    # Assert
    assert len(alerts(factory)) == 1
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AlertLog)) == 5
