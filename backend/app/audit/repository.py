from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit.models import AuditLog


def list_audit_logs(db: Session, page: int, page_size: int):
    total = db.scalar(select(func.count()).select_from(AuditLog))
    query = select(
        AuditLog.id, AuditLog.author_id, AuditLog.action,
        AuditLog.entity_type, AuditLog.entity_id, AuditLog.occurred_at,
        AuditLog.old_role, AuditLog.new_role,
    ).order_by(AuditLog.occurred_at.desc(), AuditLog.id.desc())
    rows = db.execute(query.offset((page - 1) * page_size).limit(page_size)).mappings().all()
    return total, rows
