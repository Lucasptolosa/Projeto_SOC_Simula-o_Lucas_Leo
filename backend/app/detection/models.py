from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DetectionRuleRecord(Base):
    __tablename__ = "detection_rules"
    __table_args__ = (
        CheckConstraint("id IN ('DR01', 'DR02', 'DR03')", name="ck_detection_rules_type"),
        CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="ck_detection_rules_status"),
        CheckConstraint("(id = 'DR01' AND severity = 'HIGH') OR (id IN ('DR02', 'DR03') AND severity = 'MEDIUM')", name="ck_detection_rules_severity"),
    )

    id: Mapped[str] = mapped_column(String(4), primary_key=True)
    status: Mapped[str] = mapped_column(String(8), nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)


class DetectionState(Base):
    __tablename__ = "detection_state"
    __table_args__ = (CheckConstraint("id = 1", name="ck_detection_state_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)


class AlertRecord(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        CheckConstraint("severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')", name="ck_alerts_severity"),
        CheckConstraint("status IN ('NEW', 'IN_REVIEW', 'DISMISSED', 'ESCALATED')", name="ck_alerts_status"),
        UniqueConstraint("rule_id", "trigger_event_id", name="uq_alerts_rule_trigger"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    rule_id: Mapped[str] = mapped_column(String(4), ForeignKey("detection_rules.id", ondelete="RESTRICT"), nullable=False)
    asset_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False)
    username: Mapped[str] = mapped_column(Text, nullable=False)
    trigger_event_id: Mapped[str] = mapped_column(Text, ForeignKey("logs.event_id", ondelete="RESTRICT"), nullable=False)
    severity: Mapped[str] = mapped_column(String(8), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(11), nullable=False, default="NEW")


class AlertLog(Base):
    __tablename__ = "alert_logs"
    __table_args__ = (
        UniqueConstraint("alert_id", "position", name="uq_alert_logs_position"),
        CheckConstraint("position >= 1", name="ck_alert_logs_position"),
    )

    alert_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("alerts.id", ondelete="RESTRICT"), primary_key=True)
    event_id: Mapped[str] = mapped_column(Text, ForeignKey("logs.event_id", ondelete="RESTRICT"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
