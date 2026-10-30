"""Cria persistência Users."""

from alembic import op
import sqlalchemy as sa


revision = "0001_create_users"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("role", sa.String(7), nullable=False),
        sa.Column("status", sa.String(8), server_default=sa.text("'ACTIVE'"), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
        sa.UniqueConstraint("username", name="uq_users_username"),
        sa.CheckConstraint("username ~ '[^[:space:]]'", name="ck_users_username_nonempty"),
        sa.CheckConstraint("role IN ('ADMIN', 'ANALYST')", name="ck_users_role"),
        sa.CheckConstraint("status IN ('ACTIVE', 'INACTIVE')", name="ck_users_status"),
        sa.CheckConstraint(
            r"password_hash ~ '^\$argon2id\$v=19\$m=[0-9]+,t=[0-9]+,p=[0-9]+\$[A-Za-z0-9+/]{22,}\$[A-Za-z0-9+/]{22,}$'",
            name="ck_users_password_hash",
        ),
    )


def downgrade() -> None:
    raise RuntimeError("Downgrade destrutivo bloqueado; preserve os dados de Users.")
