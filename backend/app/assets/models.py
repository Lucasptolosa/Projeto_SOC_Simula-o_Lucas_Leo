from enum import StrEnum
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, Enum, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.db.base import Base


class AssetType(StrEnum):
    SERVER = "SERVER"
    WORKSTATION = "WORKSTATION"
    APPLICATION = "APPLICATION"


class AssetStatus(StrEnum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


def validate_name(value: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("O nome do Asset deve ser não vazio.")
    return value


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (
        CheckConstraint("name ~ '[^[:space:]]'", name="ck_assets_name_nonempty"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[AssetType] = mapped_column(
        Enum(AssetType, native_enum=False, create_constraint=True,
             validate_strings=True, name="ck_assets_type"),
        nullable=False,
    )
    status: Mapped[AssetStatus] = mapped_column(
        Enum(AssetStatus, native_enum=False, create_constraint=True,
             validate_strings=True, name="ck_assets_status"),
        nullable=False,
    )

    @validates("name")
    def check_name(self, key: str, value: str) -> str:
        return validate_name(value)

    @validates("type")
    def check_type(self, key: str, value: AssetType | str) -> AssetType:
        return AssetType(value)

    @validates("status")
    def check_status(self, key: str, value: AssetStatus | str) -> AssetStatus:
        return AssetStatus(value)
