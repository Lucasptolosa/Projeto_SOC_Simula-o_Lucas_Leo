from concurrent.futures import ThreadPoolExecutor
import secrets
from threading import Barrier

import pytest
from sqlalchemy import func, select, text

from app.audit.models import AuditLog
from app.core.passwords import hash_password
from app.db.session import create_session_factory
from app.detection.models import AlertLog, AlertRecord
from app.incidents.models import Incident
from app.incidents.service import escalate
from app.investigations import service as investigations
from app.investigations.models import Investigation
from app.investigations.rules import InvestigationRuleError
from app.logs.models import LogRecord
from app.logs.service import import_logs
from app.users.models import User
from test_detection_persistence import record
from test_detection_transactions import committed_detection_db


@pytest.mark.parametrize("second_operation", ["escalate", "dismiss"])
def test_concurrent_decisions_are_atomic(committed_detection_db, second_operation):
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
            identifier = investigations.start(db, actor_ids[0], alert_id)["id"]
    barrier = Barrier(2)
    def compete(author, operation):
        try:
            with engine.begin() as connection:
                connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                connection.execute(text("SET LOCAL lock_timeout = '10s'"))
                with create_session_factory(connection)() as db:
                    barrier.wait(timeout=5)
                    if operation == "escalate":
                        escalate(db, author, identifier)
                    else:
                        investigations.dismiss(db, author, identifier, "legitimate")
            return operation, author
        except InvestigationRuleError:
            return "conflict", author
    # Act
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(compete, actor_ids[0], "escalate"),
                   pool.submit(compete, actor_ids[1], second_operation)]
        results = [future.result(timeout=20) for future in futures]
    # Assert
    assert sum(operation == "conflict" for operation, _ in results) == 1
    winner, author = next(result for result in results if result[0] != "conflict")
    with engine.begin() as connection:
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        with create_session_factory(connection)() as db:
            assert db.scalar(select(func.count()).select_from(AuditLog)) == 1
            audit = db.scalar(select(AuditLog))
            assert audit.author_id == author and audit.old_status == "IN_REVIEW"
            assert db.scalar(select(func.count()).select_from(Incident)) == (1 if winner == "escalate" else 0)
            alert = db.get(AlertRecord, alert_id)
            investigation = db.get(Investigation, identifier)
            if winner == "escalate":
                incident = db.scalar(select(Incident))
                assert alert.status == audit.new_status == "ESCALATED"
                assert incident.analyst_id == author and incident.opened_at == audit.occurred_at
                assert audit.action == "ALERT_ESCALATED" and investigation.justification is None
            else:
                assert alert.status == audit.new_status == "DISMISSED"
                assert audit.action == "ALERT_DISMISSED" and investigation.justification == "legitimate"
            assert db.scalar(select(func.count()).select_from(LogRecord)) == 5
            assert db.scalar(select(func.count()).select_from(AlertLog)) == 5
