import json
import secrets

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.logs import repository
from app.logs.models import LogRecord
from app.logs.schemas import LogInput
from test_logs import log_context, log_count, payload


@pytest.mark.parametrize("identifier", ["a" * 1024, "é" * 512, "😀" * 256, " " + "é" * 511 + " "],
                         ids=["ascii", "two_byte", "four_byte", "spaces"])
def test_event_id_byte_limit_preserves_original(log_context, identifier):
    # Arrange
    client, factory, asset_id, _, _, _, _ = log_context
    record = payload(asset_id, identifier)
    # Act
    response = client.post("/logs/import", json=[record])
    # Assert
    assert len(identifier.encode("utf-8")) == 1024
    assert response.status_code == 200
    assert response.json() == {"accepted": 1, "rejected": 0, "rejections": [],
        "detection": {"evaluated": 1, "rejected": 0, "rejections": [], "alerts_created": 0}}
    with factory() as db:
        assert db.get(LogRecord, identifier).event_id == identifier


@pytest.mark.parametrize("field,value", [
    ("event_id", "a" * 1025), ("event_id", "é" * 512 + "a"),
    ("event_id", "😀" * 256 + "a"), ("event_id", "é" * 513),
    ("event_id", "😀" * 257), ("event_id", "a" * 4096),
    ("event_id", "\x00event"), ("event_id", "ev\x00ent"), ("event_id", "event\x00"),
    ("username", "\x00account"), ("username", "ac\x00count"), ("username", "account\x00"),
    ("event_id", "\ud800"), ("username", "\ud800"),
], ids=["ascii_1025", "two_byte_1025", "four_byte_1025", "two_byte_1026", "four_byte_1028", "long",
        "nul_id_start", "nul_id_middle", "nul_id_end", "nul_user_start", "nul_user_middle", "nul_user_end",
        "surrogate_id", "surrogate_user"])
def test_invalid_text_is_rejected_before_log_insert(log_context, monkeypatch, caplog, field, value):
    # Arrange
    client, factory, asset_id, _, _, _, _ = log_context
    marker = secrets.token_urlsafe(24)
    invalid = payload(asset_id, "invalid", username=marker) | {field: value + marker if field == "username" else value}
    calls = []
    original = repository.insert_log

    def observe(db, record):
        calls.append(record.event_id)
        return original(db, record)

    monkeypatch.setattr(repository, "insert_log", observe)
    # Act
    records = [payload(asset_id, "before"), invalid, payload(asset_id, "after")]
    response = client.post("/logs/import", content=json.dumps(records), headers={"Content-Type": "application/json"})
    # Assert
    assert response.status_code == 200
    assert response.json() == {"accepted": 2, "rejected": 1, "rejections": [
        {"position": 2, "reason": "invalid_" + field, "detail": f"Campo {field} inválido ou ausente."},
    ], "detection": {"evaluated": 2, "rejected": 0, "rejections": [], "alerts_created": 0}}
    assert calls == ["before", "after"]
    assert log_count(factory) == 2
    with factory() as db:
        assert set(db.scalars(select(LogRecord.event_id))) == {"before", "after"}
    assert marker not in response.text + caplog.text


def test_incompressible_identifier_is_rejected_individually(log_context):
    # Arrange
    client, factory, asset_id, _, _, _, _ = log_context
    identifier = secrets.token_urlsafe(3072)
    # Act
    response = client.post("/logs/import", json=[payload(asset_id, identifier), payload(asset_id, "valid")])
    # Assert
    assert len(identifier.encode("utf-8")) == 4096
    assert response.status_code == 200
    assert response.json()["accepted"] == response.json()["rejected"] == 1
    assert response.json()["rejections"][0]["reason"] == "invalid_event_id"
    assert log_count(factory) == 1


@pytest.mark.parametrize("identifier", ["a" * 1025, "é" * 512 + "a", "😀" * 256 + "a"],
                         ids=["ascii", "two_byte", "four_byte"])
def test_database_enforces_event_id_bytes(log_context, identifier):
    # Arrange
    _, factory, asset_id, _, _, _, _ = log_context
    record = LogInput.model_validate(payload(asset_id)).model_copy(update={"event_id": identifier})
    # Act
    with factory() as db, pytest.raises(IntegrityError) as error:
        with db.begin_nested():
            repository.insert_log(db, record)
    # Assert
    assert error.value.orig.sqlstate == "23514"
    assert error.value.orig.diag.constraint_name == "ck_logs_event_id_bytes"
    assert log_count(factory) == 0


@pytest.mark.parametrize("field", ["event_id", "username"])
def test_schema_rejects_nul_without_record_echo(field):
    # Arrange
    marker = secrets.token_urlsafe(24)
    record = payload("11111111-1111-4111-8111-111111111111") | {field: marker + "\x00"}
    # Act
    with pytest.raises(ValidationError) as error:
        LogInput.model_validate(record)
    # Assert
    assert marker not in str(error.value)
