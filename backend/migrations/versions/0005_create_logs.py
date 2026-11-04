"""Cria Logs persistidos."""

from alembic import op
import sqlalchemy as sa


revision = "0005_create_logs"
down_revision = "0004_create_assets"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "logs",
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("asset_id", sa.Uuid(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(12), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("event_id", name="pk_logs"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], name="fk_logs_asset", ondelete="RESTRICT"),
        sa.CheckConstraint("event_id ~ '[^[:space:]]'", name="ck_logs_event_id_nonempty"),
        sa.CheckConstraint("octet_length(convert_to(event_id, 'UTF8')) <= 1024", name="ck_logs_event_id_bytes"),
        sa.CheckConstraint("username ~ '[^[:space:]]'", name="ck_logs_username_nonempty"),
        sa.CheckConstraint("event_type IN ('AUTH_FAILURE', 'AUTH_SUCCESS', 'ADMIN_ACCESS')", name="ck_logs_event_type"),
    )


def downgrade() -> None:
    raise RuntimeError("Downgrade destrutivo bloqueado; preserve os Logs.")
