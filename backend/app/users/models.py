from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Enum, Text, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.core.passwords import ARGON2ID_PATTERN, validate_password_hash
from app.db.base import Base


class UserRole(StrEnum):
    ADMIN = "ADMIN"
    ANALYST = "ANALYST"


class UserStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("username", name="uq_users_username"),
        CheckConstraint("username ~ '[^[:space:]]'", name="ck_users_username_nonempty"),
        CheckConstraint(
            "password_hash ~ '^" + ARGON2ID_PATTERN + "$'",
            name="ck_users_password_hash",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False, create_constraint=True,
             validate_strings=True, name="ck_users_role"),
        nullable=False,
    )
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, native_enum=False, create_constraint=True,
             validate_strings=True, name="ck_users_status"),
        nullable=False, default=UserStatus.ACTIVE, server_default=text("'ACTIVE'"),
    )
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)

    @validates("username")
    def validate_username(self, key: str, value: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("O nome de usuário deve ser não vazio.")
        return value

    @validates("role")
    def validate_role(self, key: str, value: UserRole | str) -> UserRole:
        return UserRole(value)

    @validates("status")
    def validate_status(self, key: str, value: UserStatus | str) -> UserStatus:
        return UserStatus(value)

    @validates("password_hash")
    def validate_hash(self, key: str, value: str) -> str:
        return validate_password_hash(value)
