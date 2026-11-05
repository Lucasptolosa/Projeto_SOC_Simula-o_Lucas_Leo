from typing import Annotated, Any
from datetime import datetime, timezone

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.auth.authorization import require_roles
from app.core.errors import logger
from app.core.pagination import Page
from app.logs import service
from app.logs.schemas import ImportSummary, LogInput, LogsQuery
from app.db.session import get_session
from app.users.models import User, UserRole


router = APIRouter(prefix="/logs", tags=["Logs"])
RULE_ERRORS = {
    "inactive_author": (401, "Autenticação necessária."),
    "forbidden_author": (403, "Permissão insuficiente."),
    "invalid_batch_size": (422, "O lote deve conter de 1 a 1.000 registros."),
}


@router.get("", response_model=Page[LogInput])
def list_logs(
    params: Annotated[LogsQuery, Query()],
    author: Annotated[User, Depends(require_roles(UserRole.ADMIN, UserRole.ANALYST))],
    db: Annotated[Session, Depends(get_session)],
):
    try:
        return service.list_logs(db, author.id, params)
    except service.LogQueryError as error:
        status, detail = RULE_ERRORS[str(error)]
        raise HTTPException(status_code=status, detail=detail) from None


def require_json(request: Request) -> None:
    content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if content_type != "application/json":
        logger.warning("timestamp=%s operation=/logs/import category=UnsupportedMediaType",
                       datetime.now(timezone.utc).isoformat())
        raise HTTPException(status_code=415, detail="Envie application/json.")


@router.post("/import", response_model=ImportSummary, dependencies=[Depends(require_json)])
def import_logs(
    records: Annotated[list[Any], Body(min_length=1, max_length=1000)],
    author: Annotated[User, Depends(require_roles(UserRole.ADMIN))],
    db: Annotated[Session, Depends(get_session)],
):
    try:
        result = service.import_logs(db, author.id, records)
        db.commit()
        if result.rejected:
            logger.warning("timestamp=%s operation=/logs/import category=RecordRejected rejected=%s",
                           datetime.now(timezone.utc).isoformat(), result.rejected)
        if result.detection.rejected:
            logger.warning("timestamp=%s operation=/logs/import category=DetectionRejected rejected=%s",
                           datetime.now(timezone.utc).isoformat(), result.detection.rejected)
        return result
    except service.LogImportError as error:
        db.rollback()
        status, detail = RULE_ERRORS[str(error)]
        raise HTTPException(status_code=status, detail=detail) from None
    except Exception:
        db.rollback()
        raise
