from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.alerts import service
from app.alerts.schemas import AlertDetail, AlertsQuery, DetailQuery, PublicAlert
from app.auth.authorization import require_roles
from app.core.pagination import Page
from app.db.session import get_session
from app.users.models import User, UserRole


router = APIRouter(prefix="/alerts", tags=["Consulta de Alerts"])
Analyst = Annotated[User, Depends(require_roles(UserRole.ANALYST))]
Database = Annotated[Session, Depends(get_session)]
ERRORS = {
    "inactive_author": (401, "Autenticação necessária."),
    "forbidden_author": (403, "Permissão insuficiente."),
    "not_found": (404, "Alert não encontrado."),
}


def query(operation):
    try:
        return operation()
    except service.AlertQueryError as error:
        status, detail = ERRORS[str(error)]
        raise HTTPException(status_code=status, detail=detail) from None


@router.get("", response_model=Page[PublicAlert])
def list_alerts(params: Annotated[AlertsQuery, Query()], author: Analyst, db: Database):
    return query(lambda: service.list_alerts(db, author.id, params))


@router.get("/{alert_id}", response_model=AlertDetail)
def get_alert(alert_id: UUID, params: Annotated[DetailQuery, Query()], author: Analyst, db: Database):
    return query(lambda: service.get_alert(db, author.id, alert_id))
