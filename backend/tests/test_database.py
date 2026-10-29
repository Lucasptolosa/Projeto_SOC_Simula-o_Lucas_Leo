
import pytest

from pydantic import ValidationError
from sqlalchemy import text

from app.core.config import Settings
from app.db import session as db_session
from app.db.session import create_db_engine


def test_conexao_usa_banco_de_testes(test_db_settings: Settings):
    # Arrange
    engine = create_db_engine(test_db_settings)

    try:
        # Act
        with engine.connect() as connection:
            result = connection.execute(text("SELECT current_database()"))
            database_name = result.scalar_one()

        # Assert
        assert database_name == "mini_soc_test"

    finally:
        engine.dispose()


def test_configuracao_rejeita_porta_invalida():
    # Arrange
    porta_invalida = 70000

    # Act
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            _env_file=None,
            db_host="localhost",
            db_port=porta_invalida,
            db_name="mini_soc_test",
            db_user="mini_soc_app",
            db_password="senha_ficticia",
        )

    # Assert
    erros = exc_info.value.errors()
    assert erros[0]["loc"] == ("db_port",)
    assert erros[0]["type"] == "less_than_equal"


def test_validacao_nao_expoe_valor_de_entrada():
    # Arrange
    valor_sensivel = "valor-ficticio-que-nao-deve-aparecer-no-erro"

    # Act
    with pytest.raises(ValidationError) as exc_info:
        Settings(
            _env_file=None,
            db_host="localhost",
            db_port=valor_sensivel,
            db_name="mini_soc_test",
            db_user="mini_soc_app",
            db_password="senha_ficticia",
        )

    # Assert
    assert valor_sensivel not in str(exc_info.value)


def test_fabrica_compartilhada_reutiliza_engine(test_db_settings, monkeypatch):
    # Arrange
    monkeypatch.setattr(db_session, "Settings", lambda: test_db_settings)
    db_session.get_session_factory.cache_clear()
    factory = db_session.get_session_factory()

    try:
        # Act
        same_factory = db_session.get_session_factory()
        with factory() as session:
            resultado = session.scalar(text("SELECT current_database()"))

        # Assert
        assert factory is same_factory
        assert resultado == "mini_soc_test"
    finally:
        factory.kw["bind"].dispose()
        db_session.get_session_factory.cache_clear()


def test_integracao_recusa_banco_de_desenvolvimento(monkeypatch, request):
    # Arrange: variáveis do processo prevalecem sobre o arquivo .env.test.
    monkeypatch.setenv("DB_NAME", "mini_soc_dev")

    # Act / Assert: a configuração é rejeitada antes de abrir a conexão.
    with pytest.raises(ValueError, match="Os testes devem utilizar mini_soc_test"):
        request.getfixturevalue("test_db_connection")
