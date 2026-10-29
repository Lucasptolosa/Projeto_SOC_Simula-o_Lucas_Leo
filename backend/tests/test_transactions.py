
import pytest
from sqlalchemy import insert, select

from app.db import session as db_session
from app.db.session import create_session_factory


def test_commit_persiste_registro(tabela_transacoes):
    # Arrange
    connection, tabela = tabela_transacoes
    factory = create_session_factory(connection)

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
    connection, tabela = tabela_transacoes
    factory = create_session_factory(connection)

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


@pytest.mark.parametrize("com_excecao", [False, True])
def test_dependencia_descarta_gravacao_pendente(
    tabela_transacoes, monkeypatch, com_excecao
):
    # Arrange
    connection, tabela = tabela_transacoes
    factory = create_session_factory(connection)
    monkeypatch.setattr(db_session, "get_session_factory", lambda: factory)
    dependency = db_session.get_session()
    session = next(dependency)
    session.execute(insert(tabela).values(id=1, valor="pendente"))

    # Act
    if com_excecao:
        with pytest.raises(RuntimeError, match="Falha simulada"):
            dependency.throw(RuntimeError("Falha simulada"))
    else:
        dependency.close()

    # Assert
    with factory() as verification_session:
        resultado = verification_session.execute(
            select(tabela.c.valor).where(tabela.c.id == 1)
        ).scalar_one_or_none()
    assert resultado is None
    assert not session.in_transaction()
