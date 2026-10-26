
import pytest

from pydantic import ValidationError
from sqlalchemy import text

from app.core.config import Settings
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
