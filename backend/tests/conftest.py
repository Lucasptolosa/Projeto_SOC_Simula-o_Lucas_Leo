from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, text
from sqlalchemy.engine import Connection
from sqlalchemy.schema import CreateSchema
from alembic import command
from alembic.config import Config

from app.core.config import Settings
from app.db.session import create_db_engine
from app.db.session import create_session_factory


@pytest.fixture
def test_db_settings() -> Settings:
    env_file = Path(__file__).resolve().parents[1] / ".env.test"
    if not env_file.is_file():
        raise FileNotFoundError("Arquivo backend/.env.test não encontrado.")

    settings = Settings(_env_file=env_file)
    if settings.db_name != "mini_soc_test":
        raise ValueError("Os testes devem utilizar mini_soc_test")

    return settings


@pytest.fixture
def test_db_connection(test_db_settings: Settings) -> Iterator[Connection]:
    engine = create_db_engine(test_db_settings)
    try:
        with engine.connect() as connection:
            # Confirma banco real
            database_name = connection.scalar(text("SELECT current_database()"))
            if database_name != "mini_soc_test":
                raise ValueError("A conexão de testes deve utilizar mini_soc_test")
            connection.commit()
            yield connection
    finally:
        # Libera tabelas temporárias
        engine.dispose()


@pytest.fixture
def tabela_transacoes(test_db_connection: Connection):
    tabela = Table(
        f"test_transaction_{uuid4().hex}",
        MetaData(),
        Column("id", Integer, primary_key=True),
        Column("valor", String(50), nullable=False),
        schema="pg_temp",
        prefixes=["TEMPORARY"],
        postgresql_on_commit="PRESERVE ROWS",
    )
    tabela.create(test_db_connection)
    test_db_connection.commit()
    return test_db_connection, tabela


@pytest.fixture
def users_db(test_db_connection: Connection):
    connection = test_db_connection
    schema = f"test_users_{uuid4().hex}"
    transaction = connection.begin()
    try:
        connection.execute(CreateSchema(schema))
        connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
        factory = create_session_factory(connection)
        factory.configure(join_transaction_mode="create_savepoint")
        yield factory, connection
    finally:
        # Reverte somente testes
        transaction.rollback()
        assert not connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = :schema)"),
            {"schema": schema},
        )
        connection.rollback()
