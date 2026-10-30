import secrets
from uuid import UUID, uuid4

import pytest
from argon2 import PasswordHasher
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext

from app.core.passwords import hash_password
from app.db.base import Base
from app.users.bootstrap import BootstrapError, create_initial_admin
from app.users.models import User, UserRole, UserStatus


@pytest.fixture
def encoded_password():
    return hash_password(secrets.token_urlsafe(24))


@pytest.mark.parametrize("role", list(UserRole))
def test_user_persistido(users_db, role):
    # Arrange
    factory, connection = users_db
    password = secrets.token_urlsafe(24)
    encoded = hash_password(password)

    # Act
    with factory.begin() as session:
        user = User(username="analista-ç", role=role, password_hash=encoded)
        session.add(user)
        session.flush()
        user_id = user.id
    with factory() as session:
        recovered = session.get(User, user_id)

        # Assert
        assert isinstance(recovered.id, UUID)
        assert recovered.username == "analista-ç"
        assert recovered.role is role
        assert recovered.status is UserStatus.ACTIVE
        assert recovered.password_hash != password
        assert PasswordHasher().verify(recovered.password_hash, password)
        assert "password" not in inspect(User).columns


def test_username_duplicado_preserva_original(users_db, encoded_password):
    # Arrange
    factory, _ = users_db
    with factory.begin() as session:
        original = User(username="único", role="ADMIN", password_hash=encoded_password)
        session.add(original)
        session.flush()
        original_id = original.id

    # Act
    with pytest.raises(IntegrityError) as error:
        with factory.begin() as session:
            session.add(User(username="único", role="ANALYST", password_hash=encoded_password))
            session.flush()

    # Assert
    assert encoded_password not in str(error.value)
    with factory() as session:
        users = session.scalars(select(User)).all()
        assert len(users) == 1
        assert users[0].id == original_id
        assert users[0].role is UserRole.ADMIN


@pytest.mark.parametrize("field,value", [
    ("username", ""), ("username", " \t\n"), ("username", None),
    ("role", "ROOT"), ("status", "DELETED"), ("password_hash", "texto-sem-hash"),
])
def test_modelo_valida_entrada(field, value, encoded_password):
    # Arrange
    values = dict(username="u", role="ADMIN", status="ACTIVE", password_hash=encoded_password)
    values[field] = value

    # Act
    with pytest.raises(ValueError):
        User(**values)

    # Assert
    assert set(Base.metadata.tables) == {"users"}


@pytest.mark.parametrize("field,value", [
    ("username", ""), ("username", "\t\n"), ("username", None),
    ("role", "ROOT"), ("role", None), ("status", "DELETED"), ("status", None),
    ("password_hash", "texto-sem-hash"), ("password_hash", None),
])
def test_banco_rejeita_dados_invalidos(users_db, encoded_password, field, value):
    # Arrange
    factory, _ = users_db
    values = dict(id=uuid4(), username="u", role="ADMIN", status="ACTIVE", password_hash=encoded_password)
    values[field] = value

    # Act
    with pytest.raises(IntegrityError):
        with factory.begin() as session:
            session.execute(text(
                "INSERT INTO users (id, username, role, status, password_hash) "
                "VALUES (:id, :username, :role, :status, :password_hash)"
            ), values)

    # Assert
    with factory() as session:
        assert session.scalar(select(User.id)) is None


def test_estado_inativo_e_identificadores(users_db, encoded_password):
    # Arrange
    factory, _ = users_db

    # Act
    with factory.begin() as session:
        first = User(username="a", role="ADMIN", status="INACTIVE", password_hash=encoded_password)
        second = User(username="A", role="ANALYST", password_hash=encoded_password)
        session.add_all([first, second])
        session.flush()

        # Assert
        assert first.id != second.id
        assert first.status is UserStatus.INACTIVE
        assert second.status is UserStatus.ACTIVE


def test_bootstrap_cria_admin(users_db):
    # Arrange
    factory, connection = users_db
    password = secrets.token_urlsafe(24)

    # Act
    with factory.begin() as session:
        user = create_initial_admin(session, "operador", password)
        user_id = user.id
        locked = session.scalar(text(
            "SELECT count(*) FROM pg_locks WHERE pid = pg_backend_pid() "
            "AND relation = 'users'::regclass AND mode = 'ShareRowExclusiveLock' AND granted"
        ))

    # Assert
    with factory() as session:
        user = session.get(User, user_id)
        assert user.role is UserRole.ADMIN
        assert user.status is UserStatus.ACTIVE
        assert PasswordHasher().verify(user.password_hash, password)
        assert locked == 1


@pytest.mark.parametrize("existing_role", list(UserRole))
def test_bootstrap_recusa_repeticao(users_db, encoded_password, existing_role):
    # Arrange
    factory, _ = users_db
    with factory.begin() as session:
        session.add(User(username="existente", role=existing_role, password_hash=encoded_password))

    # Act
    with pytest.raises(BootstrapError):
        with factory.begin() as session:
            create_initial_admin(session, "outro", secrets.token_urlsafe(24))

    # Assert
    with factory() as session:
        users = session.scalars(select(User)).all()
        assert len(users) == 1
        assert users[0].username == "existente"
        assert users[0].password_hash == encoded_password


def test_bootstrap_rollback(users_db):
    # Arrange
    factory, _ = users_db

    # Act
    with pytest.raises(RuntimeError):
        with factory.begin() as session:
            create_initial_admin(session, "operador", secrets.token_urlsafe(24))
            raise RuntimeError("Falha simulada")

    # Assert
    with factory() as session:
        assert session.scalar(select(User.id)) is None


def test_migration_compativel_com_metadata(users_db):
    # Arrange
    _, connection = users_db
    context = MigrationContext.configure(connection, opts={"compare_server_default": True})

    # Act
    differences = compare_metadata(context, Base.metadata)
    tables = inspect(connection).get_table_names()

    # Assert
    assert differences == []
    assert set(tables) == {"users", "alembic_version"}
    assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0001_create_users"
