from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from sqlalchemy import func, select, text

from app.audit.models import AuditLog
from app.db.session import create_session_factory
from app.detection import repository, service
from app.detection.models import AlertRecord, DetectionRuleRecord
from app.logs import service as ingestion
from test_detection_persistence import record
from test_detection_transactions import committed_detection_db


def transaction(engine, schema, operation):
    with engine.begin() as connection:
        assert connection.scalar(text("SELECT current_database()")) == "mini_soc_test"
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        connection.execute(text("SET LOCAL lock_timeout = '10s'"))
        with create_session_factory(connection)() as db:
            result = operation(db)
            db.flush()
            return result


def test_concurrent_same_status_creates_one_audit(committed_detection_db):
    # Arrange
    engine, schema, actors, _ = committed_detection_db
    barrier = Barrier(2)
    def change(actor):
        barrier.wait(timeout=5)
        return transaction(engine, schema, lambda db: service.update_rule_status(db, actor, "DR01", "INACTIVE").status)
    # Act
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(change, actor) for actor in actors]
        results = [future.result(timeout=20) for future in futures]
    # Assert
    assert results == ["INACTIVE", "INACTIVE"]
    assert transaction(engine, schema, lambda db: db.scalar(select(func.count()).select_from(AuditLog))) == 1
    assert transaction(engine, schema, lambda db: db.get(DetectionRuleRecord, "DR01").status) == "INACTIVE"


@pytest.mark.parametrize("first", ["change", "import"])
def test_import_and_change_use_confirmed_state(committed_detection_db, monkeypatch, first):
    # Arrange
    engine, schema, actors, asset_id = committed_detection_db
    held, attempted, release = Event(), Event(), Event()
    original_lock, original_target = repository.lock_state, repository.rule_by_id
    def pause(value):
        held.set()
        assert release.wait(timeout=10)
        return value
    if first == "change":
        monkeypatch.setattr(repository, "rule_by_id", lambda db, key: pause(original_target(db, key)))
        def import_lock(db):
            attempted.set()
            return original_lock(db)
        monkeypatch.setattr(service, "lock_state", import_lock)
    else:
        monkeypatch.setattr(service, "lock_state", lambda db: pause(original_lock(db)))
        def change_lock(db):
            attempted.set()
            return original_lock(db)
        monkeypatch.setattr(repository, "lock_state", change_lock)
    def change():
        return transaction(engine, schema, lambda db: service.update_rule_status(db, actors[0], "DR01", "INACTIVE").status)
    def import_batch():
        return transaction(engine, schema, lambda db: ingestion.import_logs(db, actors[1], [record(asset_id, n, n) for n in range(5)]))
    operations = {"change": change, "import": import_batch}
    # Act
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(operations[first])
        try:
            assert held.wait(timeout=10)
            second_future = pool.submit(operations["import" if first == "change" else "change"])
            assert attempted.wait(timeout=10)
            assert not second_future.done()
        finally:
            release.set()
        first_result = first_future.result(timeout=20)
        second_result = second_future.result(timeout=20)
    # Assert
    imported = second_result if first == "change" else first_result
    assert imported.accepted == 5
    assert imported.detection.alerts_created == (0 if first == "change" else 1)
    assert transaction(engine, schema, lambda db: db.get(DetectionRuleRecord, "DR01").status) == "INACTIVE"
    assert transaction(engine, schema, lambda db: db.scalar(select(func.count()).select_from(AlertRecord))) == (0 if first == "change" else 1)
    assert transaction(engine, schema, lambda db: db.scalar(select(func.count()).select_from(AuditLog))) == 1
