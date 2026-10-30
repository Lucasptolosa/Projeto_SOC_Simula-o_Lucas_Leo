
from logging.config import fileConfig

from alembic import context

from app.core.config import Settings
from app.db.session import create_db_engine


config = context.config

if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = None


def run_migrations_online() -> None:
    # Cria conexão
    engine = create_db_engine(Settings())

    try:
        with engine.connect() as connection:
            # Configura migrações
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
            )

            # Executa migrações
            with context.begin_transaction():
                context.run_migrations()
    finally:
        # Libera conexões
        engine.dispose()


if context.is_offline_mode():
    raise RuntimeError("Migrações offline não configuradas.")
else:
    run_migrations_online()
