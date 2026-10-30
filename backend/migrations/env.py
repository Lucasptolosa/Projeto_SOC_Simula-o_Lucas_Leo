
from logging.config import fileConfig

from alembic import context

from app.core.config import Settings
from app.db.session import create_db_engine
from app.db.base import Base
from app.users.models import User
from app.auth.models import AuthSession


config = context.config

if config.config_file_name:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

target_metadata = Base.metadata


def configure_connection(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    supplied_connection = config.attributes.get("connection")
    if supplied_connection is not None:
        configure_connection(supplied_connection)
        return
    # Cria conexão
    engine = create_db_engine(Settings())

    try:
        with engine.connect() as connection:
            configure_connection(connection)
    finally:
        # Libera conexões
        engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Migrações offline não configuradas.")
else:
    run_migrations_online()
