from alembic import op
import sqlalchemy as sa


revision = "0009_incident_treatment"
down_revision = "0008_create_incidents"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("incidents", sa.Column("containment_description", sa.Text(), nullable=True))
    op.add_column("incidents", sa.Column("contained_by", sa.Uuid(), nullable=True))
    op.add_column("incidents", sa.Column("contained_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("incidents", sa.Column("resolution_conclusion", sa.Text(), nullable=True))
    op.add_column("incidents", sa.Column("resolved_by", sa.Uuid(), nullable=True))
    op.add_column("incidents", sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True))
    for field in ("contained_by", "resolved_by"):
        op.create_foreign_key(f"fk_incidents_{field}", "incidents", "users", [field], ["id"], ondelete="RESTRICT")
    op.create_check_constraint(
        "ck_incidents_containment", "incidents",
        "(containment_description IS NULL AND contained_by IS NULL AND contained_at IS NULL) OR "
        "(containment_description IS NOT NULL AND contained_by IS NOT NULL AND contained_at IS NOT NULL)",
    )
    op.create_check_constraint(
        "ck_incidents_resolution", "incidents",
        "(resolution_conclusion IS NULL AND resolved_by IS NULL AND resolved_at IS NULL) OR "
        "(resolution_conclusion IS NOT NULL AND resolved_by IS NOT NULL AND resolved_at IS NOT NULL)",
    )


def downgrade() -> None:
    raise RuntimeError("Downgrade destrutivo bloqueado; preserve tratamento e auditoria.")
