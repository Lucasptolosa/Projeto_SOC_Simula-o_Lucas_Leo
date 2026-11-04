from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import secrets
import subprocess
import sys
from threading import Barrier
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.schema import CreateSchema, DropSchema

from app.assets.models import Asset
from app.core.passwords import hash_password
from app.db.session import create_db_engine, create_session_factory
from app.detection.models import AlertLog, AlertRecord, DetectionState
from app.logs import service
from app.logs.models import LogRecord
from app.users.models import User
from test_detection_persistence import record


@pytest.fixture
def committed_detection_db(test_db_settings):
    engine = create_db_engine(test_db_settings)
    schema = "test_detection_" + uuid4().hex
    created = False
    try:
        with engine.begin() as connection:
            assert connection.scalar(text("SELECT current_database()")) == "mini_soc_test"
            connection.execute(CreateSchema(schema))
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            config.attributes["connection"] = connection
            command.upgrade(config, "head")
            with create_session_factory(connection)() as db:
                actors = [User(username=f"admin-{n}", role="ADMIN", password_hash=hash_password(secrets.token_urlsafe(24))) for n in range(2)]
                asset = Asset(name="committed", type="SERVER", status="ACTIVE")
                db.add_all([*actors, asset])
                db.flush()
                actor_ids, asset_id = [actor.id for actor in actors], asset.id
        created = True
        yield engine, schema, actor_ids, asset_id
    finally:
        if created:
            with engine.begin() as connection:
                assert connection.scalar(text("SELECT current_database()")) == "mini_soc_test"
                assert schema.startswith("test_detection_") and len(schema) == 47
                connection.execute(DropSchema(schema, cascade=True))
        engine.dispose()


def test_two_admins_concurrently_import_same_sequence_once(committed_detection_db):
    # Arrange
    engine, schema, actor_ids, asset_id = committed_detection_db
    barrier = Barrier(2)
    records = [record(asset_id, n, n) for n in range(5)]
    def competitor(actor):
        with engine.begin() as connection:
            connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
            connection.execute(text("SET LOCAL lock_timeout = '10s'"))
            with create_session_factory(connection)() as db:
                barrier.wait(timeout=5)
                result = service.import_logs(db, actor, records)
                db.flush()
                return result
    # Act
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(competitor, actor) for actor in actor_ids]
        results = [future.result(timeout=20) for future in futures]
    # Assert
    assert sorted(result.accepted for result in results) == [0, 5]
    assert sum(result.detection.alerts_created for result in results) == 1
    with engine.begin() as connection:
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        assert connection.scalar(select(func.count()).select_from(AlertRecord)) == 1
        assert connection.scalar(select(func.count()).select_from(AlertLog)) == 5
        assert connection.scalar(select(func.count()).select_from(LogRecord)) == 5


def test_process_restart_continues_confirmed_sequence(committed_detection_db):
    # Arrange
    engine, schema, actors, asset_id = committed_detection_db
    script = '''
import json, sys
from pathlib import Path
from uuid import UUID
from sqlalchemy import text
from app.core.config import Settings
from app.db.session import create_db_engine, create_session_factory
from app.logs.service import import_logs
settings = Settings(_env_file=Path('.env.test'))
assert settings.db_name == 'mini_soc_test'
engine = create_db_engine(settings)
try:
    with engine.begin() as connection:
        assert connection.scalar(text('SELECT current_database()')) == 'mini_soc_test'
        connection.execute(text('SET LOCAL search_path TO "' + sys.argv[1] + '"'))
        with create_session_factory(connection)() as db:
            result = import_logs(db, UUID(sys.argv[2]), json.load(sys.stdin))
            db.flush()
    print(result.model_dump_json())
finally:
    engine.dispose()
'''
    def run(records):
        result = subprocess.run([sys.executable, "-c", script, schema, str(actors[0])],
            input=json.dumps(records), capture_output=True, text=True, timeout=30,
            cwd=Path(__file__).resolve().parents[1])
        assert result.returncode == 0, "Processo isolado falhou."
        return json.loads(result.stdout)
    # Act
    first = run([record(asset_id, n, n) for n in range(4)])
    second = run([record(asset_id, 4, 4)])
    third = run([record(asset_id, 5, 5)])
    # Assert
    assert first["detection"]["alerts_created"] == 0
    assert second["detection"]["alerts_created"] == 1
    assert third["detection"]["alerts_created"] == 0
    with engine.begin() as connection:
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        assert connection.scalar(select(func.count()).select_from(AlertRecord)) == 1
        assert connection.scalar(select(func.count()).select_from(DetectionState)) == 1


def test_migration_does_not_backfill_historical_logs(test_db_connection):
    # Arrange
    connection = test_db_connection
    transaction = connection.begin()
    schema = "test_detection_" + uuid4().hex
    try:
        connection.execute(CreateSchema(schema))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.attributes["connection"] = connection
        command.upgrade(config, "0005_create_logs")
        asset_id = uuid4()
        connection.execute(Asset.__table__.insert().values(id=asset_id, name="history", type="SERVER", status="ACTIVE"))
        values = [dict(event_id=f"old-{n}", asset_id=asset_id, occurred_at="2026-11-03T12:00:00Z",
                       event_type="AUTH_FAILURE", username="history") for n in range(5)]
        connection.execute(LogRecord.__table__.insert(), values)
        # Act
        command.upgrade(config, "head")
        # Assert
        assert connection.scalar(select(func.count()).select_from(LogRecord)) == 5
        assert connection.scalar(select(func.count()).select_from(AlertRecord)) == 0
        assert connection.scalar(select(DetectionState.payload))["dr01_sequence"] == []
    finally:
        transaction.rollback()
