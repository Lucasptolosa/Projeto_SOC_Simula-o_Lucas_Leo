
from uuid import uuid4

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, insert, select

from app.core.config import Settings
from app.db.session import create_db_engine, create_session_factory


@pytest.fixture
def tabela_transacoes(test_db_settings: Settings):
    engine = create_db_engine(test_db_settings)
    metadata = MetaData()

    # Evita conflitos entre tabelas de teste.
    tabela = Table(
        f"test_transaction_{uuid4().hex}",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("valor", String(50), nullable=False),
    )

    try:
        metadata.create_all(engine)
        yield engine, tabela
    finally:
        # Remove os dados temporários.
        try:
            metadata.drop_all(engine)
        finally:
            engine.dispose()


def test_commit_persiste_registro(tabela_transacoes):
    # Arrange
    engine, tabela = tabela_transacoes
    factory = create_session_factory(engine)

    # Act
    with factory() as session:
        session.execute(insert(tabela).values(id=1, valor="confirmado"))
        session.commit()

    with factory() as session:
        resultado = session.execute(
            select(tabela.c.valor).where(tabela.c.id == 1)
        ).scalar_one_or_none()

    # Assert
    assert resultado == "confirmado"


def test_rollback_descarta_registro(tabela_transacoes):
    # Arrange
    engine, tabela = tabela_transacoes
    factory = create_session_factory(engine)

    # Act
    with factory() as session:
        session.execute(insert(tabela).values(id=1, valor="descartado"))
        session.rollback()

    with factory() as session:
        resultado = session.execute(
            select(tabela.c.valor).where(tabela.c.id == 1)
        ).scalar_one_or_none()

    # Assert
    assert resultado is None
