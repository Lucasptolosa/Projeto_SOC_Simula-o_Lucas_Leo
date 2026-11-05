from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import secrets
from threading import Barrier
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateSchema

from app.audit.models import AuditLog
from app.core.passwords import hash_password
from app.db.session import create_session_factory
from app.detection.models import AlertRecord
from app.investigations import service
from app.investigations.models import Investigation, Observation
from app.investigations.rules import InvestigationRuleError
from app.logs.service import import_logs
from app.users.models import User
from test_detection_persistence import record
from test_detection_transactions import committed_detection_db
from test_investigations import investigation_context, start, count
from test_logs import log_context


@pytest.mark.parametrize("operation", ["start", "dismiss"])
def test_concurrent_analysts_have_one_transition(committed_detection_db, operation):
    # Arrange
    engine, schema, admins, asset_id = committed_detection_db
    with engine.begin() as connection:
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        with create_session_factory(connection)() as db:
            encoded = hash_password(secrets.token_urlsafe(24))
            actors = [User(username=f"analyst-{n}", role="ANALYST", password_hash=encoded) for n in range(2)]
            db.add_all(actors)
            db.flush()
            actor_ids = [actor.id for actor in actors]
            import_logs(db, admins[0], [record(asset_id, n, n) for n in range(5)])
            alert_id = db.scalar(select(AlertRecord.id))
            identifier = service.start(db, actor_ids[0], alert_id)["id"] if operation == "dismiss" else None
    barrier = Barrier(2)
    def compete(author_id):
        try:
            with engine.begin() as connection:
                connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                connection.execute(text("SET LOCAL lock_timeout = '10s'"))
                with create_session_factory(connection)() as db:
                    barrier.wait(timeout=5)
                    if operation == "start":
                        service.start(db, author_id, alert_id)
                    else:
                        service.dismiss(db, author_id, identifier, "legitimate")
            return "success"
        except InvestigationRuleError:
            return "conflict"
    # Act
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(compete, author) for author in actor_ids]
        results = [future.result(timeout=20) for future in futures]
    # Assert
    assert sorted(results) == ["conflict", "success"]
    with engine.begin() as connection:
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        assert connection.scalar(select(func.count()).select_from(Investigation)) == 1
        assert connection.scalar(select(func.count()).select_from(AuditLog)) == (1 if operation == "dismiss" else 0)
        assert connection.scalar(select(AlertRecord.status)) == ("DISMISSED" if operation == "dismiss" else "IN_REVIEW")


def test_additive_migration_preserves_existing_role_audit(test_db_connection):
    # Arrange
    connection = test_db_connection
    transaction = connection.begin()
    schema = "test_inv_migration_" + uuid4().hex
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    config.attributes["connection"] = connection
    user_id, audit_id = uuid4(), uuid4()
    try:
        connection.execute(CreateSchema(schema))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        command.upgrade(config, "0006_detection_persistence")
        connection.execute(text("INSERT INTO users (id, username, role, status, password_hash) VALUES (:id, 'legacy', 'ADMIN', 'ACTIVE', :encoded)"),
                           {"id": user_id, "encoded": hash_password(secrets.token_urlsafe(24))})
        connection.execute(text("INSERT INTO audit_logs (id, author_id, action, entity_type, entity_id, occurred_at, old_role, new_role) "
                                "VALUES (:id, :author, 'USER_UPDATED', 'USER', :entity, now(), 'ANALYST', 'ADMIN')"),
                           {"id": audit_id, "author": user_id, "entity": str(user_id)})
        before = connection.execute(text("SELECT id, author_id, action, occurred_at, old_role, new_role FROM audit_logs")).one()
        # Act
        command.upgrade(config, "head")
        # Assert
        after = connection.execute(text("SELECT id, author_id, action, occurred_at, old_role, new_role FROM audit_logs")).one()
        assert after == before
        assert connection.execute(text("SELECT old_status, new_status FROM audit_logs")).one() == (None, None)
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0008_create_incidents"
    finally:
        transaction.rollback()


@pytest.mark.parametrize("changes", [
    {"old_status": "IN_REVIEW"},
    {"new_status": "DISMISSED"},
    {"old_status": "", "new_status": "DISMISSED"},
    {"old_status": "IN_REVIEW", "new_status": "DISMISSED", "old_role": "ANALYST", "new_role": "ADMIN"},
])
def test_audit_constraints_prevent_invalid_status_pairs(investigation_context, changes):
    # Arrange
    _, factory, alert_id, analyst_id, *_ = investigation_context
    # Act
    with pytest.raises(IntegrityError), factory.begin() as db:
        db.add(AuditLog(author_id=analyst_id, action="ALERT_DISMISSED", entity_type="ALERT",
                        entity_id=str(alert_id), occurred_at=datetime.now(timezone.utc), **changes))
    # Assert
    assert count(factory, AuditLog) == 0


def test_independent_analyst_can_append_and_dismiss(investigation_context):
    # Arrange
    client, factory, alert_id, analyst_id, *_ = investigation_context
    identifier = UUID(start(client, alert_id))
    with factory.begin() as db:
        actor = User(username="other-analyst", role="ANALYST", password_hash=hash_password(secrets.token_urlsafe(24)))
        db.add(actor)
        db.flush()
        author = actor.id
    # Act
    with factory.begin() as db:
        service.add_observation(db, author, identifier, "Independent review")
        service.dismiss(db, author, identifier, "Authorized activity")
    # Assert
    with factory() as db:
        row = db.get(Investigation, identifier)
        assert row.analyst_id == analyst_id and row.dismissed_by == author
        assert db.scalar(select(Observation.analyst_id)) == author


def test_pending_changes_rollback_when_session_closes(investigation_context):
    # Arrange
    _, factory, alert_id, analyst_id, *_ = investigation_context
    # Act
    with factory() as db:
        service.start(db, analyst_id, alert_id)
    # Assert
    assert count(factory, Investigation) == 0
    with factory() as db:
        assert db.get(AlertRecord, alert_id).status == "NEW"


def test_direct_invalid_text_never_reaches_persistence(investigation_context):
    # Arrange
    client, factory, alert_id, analyst_id, *_ = investigation_context
    identifier = UUID(start(client, alert_id))
    # Act
    with factory() as db, pytest.raises(service.InvestigationServiceError):
        service.add_observation(db, analyst_id, identifier, "bad\x00note")
    with factory() as db, pytest.raises(service.InvestigationServiceError):
        service.dismiss(db, analyst_id, identifier, "bad\x00reason")
    # Assert
    assert count(factory, Observation) == count(factory, AuditLog) == 0
    with factory() as db:
        assert db.get(AlertRecord, alert_id).status == "IN_REVIEW"


def test_service_refreshes_cached_identity(investigation_context):
    # Arrange
    _, factory, alert_id, analyst_id, *_ = investigation_context
    with factory() as db:
        cached = db.get(User, analyst_id)
        assert cached.role.value == "ANALYST"
        with factory.begin() as other:
            other.get(User, analyst_id).role = "ADMIN"
        # Act
        with pytest.raises(service.InvestigationServiceError) as error:
            service.start(db, analyst_id, alert_id)
        # Assert
        assert str(error.value) == "forbidden_author"
    assert count(factory, Investigation) == 0


def test_database_audit_failure_reverts_status_and_justification(investigation_context, monkeypatch):
    # Arrange
    client, factory, alert_id, *_ = investigation_context
    identifier = start(client, alert_id)
    original = service.append_audit
    def invalid_author(db, **values):
        values["author_id"] = uuid4()
        original(db, **values)
    monkeypatch.setattr(service, "append_audit", invalid_author)
    # Act
    response = client.post(f"/investigations/{identifier}/false-positive", json={"justification": "legitimate"})
    # Assert
    assert response.status_code == 500 and count(factory, AuditLog) == 0
    body = client.get(f"/investigations/{identifier}").json()
    assert body["status"] == "IN_REVIEW" and body["justification"] is None


@pytest.mark.parametrize("method", ["delete", "patch"])
@pytest.mark.parametrize("suffix", ["", "/observations"])
def test_no_edit_or_delete_operations(investigation_context, method, suffix):
    # Arrange
    client, factory, alert_id, *_ = investigation_context
    identifier = start(client, alert_id)
    client.post(f"/investigations/{identifier}/observations", json={"content": "preserved"})
    # Act
    response = client.request(method, f"/investigations/{identifier}{suffix}", json={"content": "changed"})
    # Assert
    assert response.status_code == 405 and count(factory, Observation) == 1
    assert client.get(f"/investigations/{identifier}/observations").json()["items"][0]["content"] == "preserved"
