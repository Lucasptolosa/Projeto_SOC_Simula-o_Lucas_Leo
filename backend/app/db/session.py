
from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine, URL
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings


def create_db_engine(settings: Settings) -> Engine:
    url = URL.create(
        drivername="postgresql+psycopg",
        username=settings.db_user,
        password=settings.db_password.get_secret_value(),
        host=settings.db_host,
        port=settings.db_port,
        database=settings.db_name,
    )

    return create_engine(
        url,
        pool_pre_ping=True,
        hide_parameters=True,
        isolation_level="READ COMMITTED",
        connect_args={"connect_timeout": 5},
    )


def create_session_factory(engine: Engine | Connection) -> sessionmaker[Session]:
    return sessionmaker(bind=engine)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    engine = create_db_engine(Settings())
    return create_session_factory(engine)


def get_session() -> Iterator[Session]:
    """Disponibiliza uma sessão; o serviço controla commit e rollback.

    Ao encerrar a dependência, fecha a sessão e desfaz gravações pendentes,
    inclusive quando a operação termina com uma exceção.
    """
    factory = get_session_factory()

    with factory() as session:
        yield session
