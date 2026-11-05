from alembic import op
import sqlalchemy as sa


revision = "0008_create_incidents"
down_revision = "0007_create_investigations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "incidents",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("alert_id", sa.Uuid(), sa.ForeignKey("alerts.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("analyst_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("severity", sa.String(8), nullable=False),
        sa.Column("status", sa.Enum("OPEN", "UNDER_INVESTIGATION", "CONTAINED", "RESOLVED",
                                   native_enum=False, create_constraint=True, validate_strings=True,
                                   name="ck_incidents_status"), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("alert_id", name="uq_incidents_alert"),
        sa.CheckConstraint("severity IN ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')", name="ck_incidents_severity"),
    )


def downgrade() -> None:
    raise RuntimeError("Downgrade destrutivo bloqueado; preserve Incidents e histórico.")
