from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.audit import service
from app.audit.schemas import PublicAuditLog
from app.auth.authorization import require_roles
from app.core.pagination import Page, PaginationQuery
from app.db.session import get_session
from app.users.models import User, UserRole


router = APIRouter(prefix="/audit-logs", tags=["Consulta de auditoria"])


@router.get("", response_model=Page[PublicAuditLog])
def list_audit_logs(
    params: Annotated[PaginationQuery, Query()],
    author: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    db: Annotated[Session, Depends(get_session)],
):
    return service.list_audit_logs(db, params.page, params.page_size)
