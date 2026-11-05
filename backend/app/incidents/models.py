from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.incidents.transitions import IncidentStatus


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        UniqueConstraint("alert_id", name="uq_incidents_alert"),
        CheckConstraint("severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')", name="ck_incidents_severity"),
        CheckConstraint(
            "(containment_description IS NULL AND contained_by IS NULL AND contained_at IS NULL) OR "
            "(containment_description IS NOT NULL AND contained_by IS NOT NULL AND contained_at IS NOT NULL)",
            name="ck_incidents_containment",
        ),
        CheckConstraint(
            "(resolution_conclusion IS NULL AND resolved_by IS NULL AND resolved_at IS NULL) OR "
            "(resolution_conclusion IS NOT NULL AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL)",
            name="ck_incidents_resolution",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    alert_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("alerts.id", ondelete="RESTRICT"), nullable=False,
    )
    analyst_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False,
    )
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[IncidentStatus] = mapped_column(
        Enum(IncidentStatus, native_enum=False, create_constraint=True,
             validate_strings=True, name="ck_incidents_status"),
        nullable=False, default=IncidentStatus.OPEN,
    )
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    containment_description: Mapped[str | None] = mapped_column(Text)
    contained_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    contained_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_conclusion: Mapped[str | None] = mapped_column(Text)
    resolved_by: Mapped[UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
