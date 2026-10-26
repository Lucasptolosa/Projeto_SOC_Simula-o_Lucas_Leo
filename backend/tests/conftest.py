from pathlib import Path
import pytest
from app.core.config import Settings

@pytest.fixture
def test_db_settings() -> Settings:
    env_file = Path(__file__).resolve().parents[1]/ ".env.test"

    if not env_file.is_file():
        raise FileNotFoundError("Arquivo backend/.env.test não encontrado.")

    settings = Settings(_env_file=env_file)
#garantir que não use o banco real
    if settings.db_name != "mini_soc_test":
        raise ValueError("Os testes devem utilizar mini_soc_test")



    return settings