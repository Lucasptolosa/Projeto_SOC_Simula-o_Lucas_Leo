from alembic import op
import sqlalchemy as sa


revision = "0007_create_investigations"
down_revision = "0006_detection_persistence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("audit_logs", sa.Column("old_status", sa.Text(), nullable=True))
    op.add_column("audit_logs", sa.Column("new_status", sa.Text(), nullable=True))
    op.create_check_constraint(
        "ck_audit_logs_status_pair", "audit_logs",
        "(old_status IS NULL AND new_status IS NULL) OR "
        "(old_status IS NOT NULL AND new_status IS NOT NULL AND old_status <> '' AND new_status <> '')",
    )
    op.create_check_constraint("ck_audit_logs_change_kind", "audit_logs", "old_role IS NULL OR old_status IS NULL")
    op.create_table(
        "investigations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("alert_id", sa.Uuid(), sa.ForeignKey("alerts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("analyst_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("justification", sa.Text(), nullable=True),
        sa.Column("dismissed_by", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("alert_id"),
        sa.CheckConstraint(
            "(justification IS NULL AND dismissed_by IS NULL AND dismissed_at IS NULL) OR "
            "(justification IS NOT NULL AND justification ~ '[^[:space:]]' "
            "AND dismissed_by IS NOT NULL AND dismissed_at IS NOT NULL)",
            name="ck_investigations_dismissal",
        ),
    )
    op.create_table(
        "investigation_observations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("investigation_id", sa.Uuid(), sa.ForeignKey("investigations.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("analyst_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("content ~ '[^[:space:]]'", name="ck_observations_content"),
    )
    op.create_index("ix_investigation_observations_investigation_id", "investigation_observations", ["investigation_id"])


def downgrade() -> None:
    raise RuntimeError("Downgrade destrutivo bloqueado; preserve investigações e auditoria.")
