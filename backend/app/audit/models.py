from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, Enum, ForeignKey, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.users.models import UserRole


class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        CheckConstraint("action <> '' AND entity_type <> '' AND entity_id <> ''", name="ck_audit_logs_required"),
        CheckConstraint(
            "(old_role IS NULL AND new_role IS NULL) OR (old_role IS NOT NULL AND new_role IS NOT NULL)",
            name="ck_audit_logs_roles_pair",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    author_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("users.id", name="fk_audit_logs_author", ondelete="RESTRICT"), nullable=False,
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    entity_id: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    old_role: Mapped[UserRole | None] = mapped_column(
        Enum(UserRole, native_enum=False, create_constraint=True, validate_strings=True, name="ck_audit_logs_old_role"),
    )
    new_role: Mapped[UserRole | None] = mapped_column(
        Enum(UserRole, native_enum=False, create_constraint=True, validate_strings=True, name="ck_audit_logs_new_role"),
    )
