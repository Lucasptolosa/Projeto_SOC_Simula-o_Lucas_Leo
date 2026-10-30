"""Cria auditoria compartilhada."""

from alembic import op
import sqlalchemy as sa


revision = "0003_create_audit_logs"
down_revision = "0002_create_auth_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("author_id", sa.Uuid(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("old_role", sa.String(7), nullable=True),
        sa.Column("new_role", sa.String(7), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_audit_logs"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], name="fk_audit_logs_author", ondelete="RESTRICT"),
        sa.CheckConstraint("action <> '' AND entity_type <> '' AND entity_id <> ''", name="ck_audit_logs_required"),
        sa.CheckConstraint(
            "(old_role IS NULL AND new_role IS NULL) OR (old_role IS NOT NULL AND new_role IS NOT NULL)",
            name="ck_audit_logs_roles_pair",
        ),
        sa.CheckConstraint("old_role IN ('ADMIN', 'ANALYST')", name="ck_audit_logs_old_role"),
        sa.CheckConstraint("new_role IN ('ADMIN', 'ANALYST')", name="ck_audit_logs_new_role"),
    )


def downgrade() -> None:
    raise RuntimeError("Downgrade destrutivo bloqueado; preserve os Audit Logs.")
