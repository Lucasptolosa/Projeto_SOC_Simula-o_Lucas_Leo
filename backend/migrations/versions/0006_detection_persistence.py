"""Persiste catálogo, estado e Alerts sem reprocessar Logs históricos."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = "0006_detection_persistence"
down_revision = "0005_create_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    rules = op.create_table(
        "detection_rules",
        sa.Column("id", sa.String(4), primary_key=True),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("severity", sa.String(8), nullable=False),
        sa.CheckConstraint("id IN ('DR01', 'DR02', 'DR03')", name="ck_detection_rules_type"),
        sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="ck_detection_rules_status"),
        sa.CheckConstraint("(id = 'DR01' AND severity = 'HIGH') OR (id IN ('DR02', 'DR03') AND severity = 'MEDIUM')", name="ck_detection_rules_severity"),
    )
    state = op.create_table(
        "detection_state",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("payload", JSONB(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_detection_state_singleton"),
    )
    op.bulk_insert(rules, [dict(id=rule, status="ACTIVE", severity=severity)
                           for rule, severity in (("DR01", "HIGH"), ("DR02", "MEDIUM"), ("DR03", "MEDIUM"))])
    op.bulk_insert(state, [dict(id=1, payload={
        "version": 1, "dr01_sequence": [], "dr01_alerted": [], "dr02_failures": [],
        "prev_batch_max_time": [], "alert_id_counter": 1,
    })])
    op.create_table(
        "alerts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("rule_id", sa.String(4), sa.ForeignKey("detection_rules.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("assets.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("trigger_event_id", sa.Text(), sa.ForeignKey("logs.event_id", ondelete="RESTRICT"), nullable=False),
        sa.Column("severity", sa.String(8), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(11), nullable=False),
        sa.CheckConstraint("severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')", name="ck_alerts_severity"),
        sa.CheckConstraint("status IN ('NEW', 'IN_REVIEW', 'DISMISSED', 'ESCALATED')", name="ck_alerts_status"),
        sa.UniqueConstraint("rule_id", "trigger_event_id", name="uq_alerts_rule_trigger"),
    )
    op.create_table(
        "alert_logs",
        sa.Column("alert_id", sa.Uuid(), sa.ForeignKey("alerts.id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("event_id", sa.Text(), sa.ForeignKey("logs.event_id", ondelete="RESTRICT"), primary_key=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.CheckConstraint("position >= 1", name="ck_alert_logs_position"),
        sa.UniqueConstraint("alert_id", "position", name="uq_alert_logs_position"),
    )


def downgrade() -> None:
    raise RuntimeError("Downgrade destrutivo bloqueado; preserve estado, regras e Alerts.")
