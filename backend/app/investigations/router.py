from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.authorization import require_roles
from app.core.pagination import Page, PaginationQuery
from app.db.session import get_session
from app.investigations import service
from app.investigations.rules import InvestigationRuleError
from app.investigations.schemas import (
    FalsePositiveInput, InvestigationDetail, ObservationInput, PublicInvestigation, PublicObservation,
    StartInvestigationInput,
)
from app.users.models import User, UserRole


router = APIRouter(prefix="/investigations", tags=["Investigations"])
Analyst = Annotated[User, Depends(require_roles(UserRole.ANALYST))]
Database = Annotated[Session, Depends(get_session)]
ERRORS = {
    "inactive_author": (401, "Autenticação necessária."),
    "forbidden_author": (403, "Permissão insuficiente."),
    "not_found": (404, "Registro não encontrado."),
    "already_exists": (409, "Investigação já existente."),
    "invalid_text": (422, "Texto inválido."),
}


def run_operation(db: Session, operation: Callable, schema: type[BaseModel], *, commit: bool = False):
    try:
        result = schema.model_validate(operation())
        if commit:
            db.commit()
        return result
    except service.InvestigationServiceError as error:
        db.rollback()
        status, detail = ERRORS[str(error)]
        raise HTTPException(status_code=status, detail=detail) from None
    except InvestigationRuleError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Operação incompatível com o estado do Alert.") from None
    except Exception:
        db.rollback()
        raise


@router.post("", response_model=PublicInvestigation, status_code=201)
def start(payload: StartInvestigationInput, author: Analyst, db: Database):
    return run_operation(db, lambda: service.start(db, author.id, payload.alert_id),
                         PublicInvestigation, commit=True)


@router.get("/{investigation_id}", response_model=InvestigationDetail)
def get(investigation_id: UUID, author: Analyst, db: Database):
    return run_operation(db, lambda: service.get(db, author.id, investigation_id), InvestigationDetail)


@router.post("/{investigation_id}/observations", response_model=PublicObservation, status_code=201)
def observe(investigation_id: UUID, payload: ObservationInput, author: Analyst, db: Database):
    return run_operation(db, lambda: service.add_observation(db, author.id, investigation_id, payload.content),
                         PublicObservation, commit=True)


@router.get("/{investigation_id}/observations", response_model=Page[PublicObservation])
def observations(investigation_id: UUID, params: Annotated[PaginationQuery, Query()],
                 author: Analyst, db: Database):
    return run_operation(db, lambda: service.list_observations(
        db, author.id, investigation_id, params.page, params.page_size,
    ), Page[PublicObservation])


@router.post("/{investigation_id}/false-positive", response_model=PublicInvestigation)
def dismiss(investigation_id: UUID, payload: FalsePositiveInput, author: Analyst, db: Database):
    return run_operation(db, lambda: service.dismiss(db, author.id, investigation_id, payload.justification),
                         PublicInvestigation, commit=True)
