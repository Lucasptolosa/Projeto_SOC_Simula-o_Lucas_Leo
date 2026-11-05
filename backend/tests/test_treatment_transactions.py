from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import secrets
from threading import Barrier
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.schema import CreateSchema

from app.audit.models import AuditLog
from app.core.passwords import hash_password
from app.db.session import create_session_factory
from app.detection.models import AlertLog, AlertRecord
from app.incidents import service
from app.incidents.models import Incident
from app.incidents.schemas import TransitionInput
from app.incidents.transitions import IncidentTransitionError
from app.investigations import service as investigations
from app.investigations.models import Observation
from app.logs.models import LogRecord
from app.logs.service import import_logs
from app.users.models import User
from test_detection_persistence import record
from test_detection_transactions import committed_detection_db


@pytest.mark.parametrize("targets", [
    ("UNDER_INVESTIGATION", "UNDER_INVESTIGATION"),
    ("CONTAINED", "CONTAINED"),
    ("RESOLVED", "RESOLVED"),
    ("CONTAINED", "RESOLVED"),
])
def test_concurrent_treatment_uses_locked_current_state(committed_detection_db, targets):
    # Arrange
    engine, schema, admins, asset_id = committed_detection_db
    with engine.begin() as connection:
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        with create_session_factory(connection)() as db:
            actors = [User(username=f"handler-{n}", role="ANALYST", password_hash=hash_password(secrets.token_urlsafe(24))) for n in range(2)]
            db.add_all(actors)
            db.flush()
            authors = [actor.id for actor in actors]
            import_logs(db, admins[0], [record(asset_id, n, n) for n in range(5)])
            alert_id = db.scalar(select(AlertRecord.id))
            investigation = investigations.start(db, authors[0], alert_id)["id"]
            investigations.add_observation(db, authors[0], investigation, "original")
            incident = service.escalate(db, authors[0], investigation)
            identifier, opened_at = incident.id, incident.opened_at
            if targets[0] != "UNDER_INVESTIGATION":
                service.transition(db, authors[0], identifier, TransitionInput(target_status="UNDER_INVESTIGATION"))
    baseline = 1 if targets[0] == "UNDER_INVESTIGATION" else 2
    barrier = Barrier(2)
    def compete(author, target):
        try:
            with engine.begin() as connection:
                connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                connection.execute(text("SET LOCAL lock_timeout = '10s'"))
                with create_session_factory(connection)() as db:
                    cached = db.get(Incident, identifier)
                    fields = {"containment_description": "isolated"} if target == "CONTAINED" else (
                        {"resolution_conclusion": "fixed"} if target == "RESOLVED" else {})
                    barrier.wait(timeout=5)
                    service.transition(db, author, identifier, TransitionInput(target_status=target, **fields))
                    assert cached.status.value == target
            return target, author
        except IncidentTransitionError:
            return "conflict", author
    # Act
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(compete, author, target) for author, target in zip(authors, targets)]
        results = [future.result(timeout=20) for future in futures]
    # Assert
    successes = [(target, author) for target, author in results if target != "conflict"]
    if targets == ("CONTAINED", "RESOLVED"):
        assert sorted(target for target, _ in successes) in [["RESOLVED"], ["CONTAINED", "RESOLVED"]]
    else:
        assert len(successes) == 1 and sum(target == "conflict" for target, _ in results) == 1
    with engine.begin() as connection:
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        with create_session_factory(connection)() as db:
            row = db.get(Incident, identifier)
            assert row.analyst_id == authors[0] and row.opened_at == opened_at
            assert db.get(AlertRecord, alert_id).status == "ESCALATED"
            audits = db.scalars(select(AuditLog).where(AuditLog.entity_type == "INCIDENT").order_by(AuditLog.occurred_at)).all()
            concurrent = audits if baseline == 1 else audits[1:]
            assert db.scalar(select(func.count()).select_from(AuditLog)) == baseline + len(successes)
            assert {(a.new_status, a.author_id) for a in concurrent} == set(successes)
            for previous, following in zip(audits, audits[1:]):
                assert previous.new_status == following.old_status
            assert row.status.value == audits[-1].new_status
            if row.contained_by is not None:
                audit = next(a for a in audits if a.new_status == "CONTAINED")
                assert row.contained_by == audit.author_id and row.contained_at == audit.occurred_at
                assert row.containment_description == "isolated"
            if row.resolved_by is not None:
                assert row.resolved_by == audits[-1].author_id and row.resolved_at == audits[-1].occurred_at
            assert db.scalar(select(func.count()).select_from(LogRecord)) == 5
            assert db.scalar(select(func.count()).select_from(AlertLog)) == 5
            assert db.scalar(select(Observation.content)) == "original"


def test_additive_migration_preserves_existing_incident(test_db_connection):
    # Arrange
    connection = test_db_connection
    transaction = connection.begin()
    schema = "test_treatment_migration_" + uuid4().hex
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["connection"] = connection
    author, asset, alert, identifier = uuid4(), uuid4(), uuid4(), uuid4()
    instant = datetime.now(timezone.utc)
    try:
        connection.execute(CreateSchema(schema))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        command.upgrade(config, "0008_create_incidents")
        connection.execute(text("INSERT INTO users (id,username,role,status,password_hash) VALUES (:id,'legacy-analyst','ANALYST','ACTIVE',:hash)"),
                           {"id": author, "hash": hash_password(secrets.token_urlsafe(24))})
        connection.execute(text("INSERT INTO assets (id,name,type,status) VALUES (:id,'legacy','SERVER','ACTIVE')"), {"id": asset})
        connection.execute(text("INSERT INTO logs (event_id,asset_id,occurred_at,event_type,username) VALUES ('legacy',:asset,:instant,'AUTH_FAILURE','monitored')"),
                           {"asset": asset, "instant": instant})
        connection.execute(text("INSERT INTO alerts (id,rule_id,asset_id,username,trigger_event_id,severity,created_at,status) "
                                "VALUES (:id,'DR01',:asset,'monitored','legacy','HIGH',:instant,'ESCALATED')"),
                           {"id": alert, "asset": asset, "instant": instant})
        connection.execute(text("INSERT INTO incidents (id,alert_id,analyst_id,severity,status,opened_at) "
                                "VALUES (:id,:alert,:author,'HIGH','OPEN',:instant)"),
                           {"id": identifier, "alert": alert, "author": author, "instant": instant})
        before = connection.execute(text("SELECT * FROM incidents")).mappings().one()
        # Act
        command.upgrade(config, "head")
        migrated = connection.execute(text("SELECT * FROM incidents")).mappings().one()
        assert all(migrated[key] == value for key, value in before.items())
        assert all(migrated[key] is None for key in set(migrated) - set(before))
        factory = create_session_factory(connection)
        factory.configure(join_transaction_mode="create_savepoint")
        with factory.begin() as db:
            service.transition(db, author, identifier, TransitionInput(target_status="UNDER_INVESTIGATION"))
            service.transition(db, author, identifier, TransitionInput(target_status="RESOLVED", resolution_conclusion="legacy resolved"))
        # Assert
        after = connection.execute(text("SELECT * FROM incidents")).mappings().one()
        assert all(after[key] == value for key, value in before.items() if key != "status")
        assert after["status"] == "RESOLVED" and after["resolution_conclusion"] == "legacy resolved"
        assert after["contained_by"] is after["contained_at"] is after["containment_description"] is None
        assert after["resolved_by"] == author and after["resolved_at"] >= instant
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0009_incident_treatment"
        assert connection.scalar(select(func.count()).select_from(AuditLog)) == 2
        assert connection.scalar(select(AlertRecord.status)) == "ESCALATED"
    finally:
        transaction.rollback()
