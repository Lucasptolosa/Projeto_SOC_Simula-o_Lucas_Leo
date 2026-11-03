from datetime import datetime
from enum import StrEnum
from uuid import UUID

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EventType(StrEnum):
    AUTH_FAILURE = "AUTH_FAILURE"
    AUTH_SUCCESS = "AUTH_SUCCESS"
    ADMIN_ACCESS = "ADMIN_ACCESS"


class LogRecord(Base):
    __tablename__ = "logs"
    __table_args__ = (
        CheckConstraint("event_id ~ '[^[:space:]]'", name="ck_logs_event_id_nonempty"),
        CheckConstraint("username ~ '[^[:space:]]'", name="ck_logs_username_nonempty"),
    )

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    asset_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("assets.id", name="fk_logs_asset", ondelete="RESTRICT"), nullable=False,
    )
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    event_type: Mapped[EventType] = mapped_column(
        Enum(EventType, native_enum=False, create_constraint=True,
             validate_strings=True, name="ck_logs_event_type"),
        nullable=False,
    )
    username: Mapped[str] = mapped_column(Text, nullable=False)
