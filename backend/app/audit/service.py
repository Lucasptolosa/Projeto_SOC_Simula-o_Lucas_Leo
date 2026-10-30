from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy.orm import Session

from app.audit.models import AuditLog
from app.users.models import UserRole


def append_audit(
    db: Session, *, author_id: UUID, action: str, entity_type: str,
    entity_id: str, old_role: UserRole | None = None, new_role: UserRole | None = None,
) -> None:
    db.add(AuditLog(
        author_id=author_id, action=action, entity_type=entity_type,
        entity_id=entity_id, occurred_at=datetime.now(timezone.utc),
        old_role=old_role, new_role=new_role,
    ))
