"""Cria Assets persistidos."""

from alembic import op
import sqlalchemy as sa


revision = "0004_create_assets"
down_revision = "0003_create_audit_logs"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("type", sa.String(11), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_assets"),
        sa.CheckConstraint("name ~ '[^[:space:]]'", name="ck_assets_name_nonempty"),
        sa.CheckConstraint("type IN ('SERVER', 'WORKSTATION', 'APPLICATION')", name="ck_assets_type"),
        sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="ck_assets_status"),
    )


def downgrade() -> None:
    raise RuntimeError("Downgrade destrutivo bloqueado; preserve os Assets.")
