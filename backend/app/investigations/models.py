from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Investigation(Base):
    __tablename__ = "investigations"
    __table_args__ = (
        CheckConstraint(
            "(justification IS NULL AND dismissed_by IS NULL AND dismissed_at IS NULL) OR "
            "(justification IS NOT NULL AND justification ~ '[^[:space:]]' "
            "AND dismissed_by IS NOT NULL AND dismissed_at IS NOT NULL)",
            name="ck_investigations_dismissal",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    alert_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("alerts.id", ondelete="RESTRICT"), nullable=False,
        unique=True,
    )
    analyst_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    justification: Mapped[str | None] = mapped_column(Text)
    dismissed_by: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"),
    )
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Observation(Base):
    __tablename__ = "investigation_observations"
    __table_args__ = (
        CheckConstraint("content ~ '[^[:space:]]'", name="ck_observations_content"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    investigation_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("investigations.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    analyst_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
