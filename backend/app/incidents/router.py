from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query

from app.core.pagination import Page
from app.incidents import service
from app.incidents.schemas import EscalationInput, IncidentsQuery, PublicIncident, TransitionInput
from app.incidents.transitions import IncidentTransitionError
from app.investigations.router import Analyst, Database, run_operation


router = APIRouter(tags=["Incidents"])


@router.post("/investigations/{investigation_id}/escalate", response_model=PublicIncident, status_code=201)
def escalate(investigation_id: UUID, author: Analyst, db: Database, payload: EscalationInput | None = None):
    return run_operation(db, lambda: service.escalate(db, author.id, investigation_id),
                         PublicIncident, commit=True)


@router.get("/incidents", response_model=Page[PublicIncident])
def list_incidents(params: Annotated[IncidentsQuery, Query()], author: Analyst, db: Database):
    return run_operation(db, lambda: service.list_incidents(db, author.id, params), Page[PublicIncident])


@router.get("/incidents/{incident_id}", response_model=PublicIncident)
def get(incident_id: UUID, author: Analyst, db: Database):
    return run_operation(db, lambda: service.get(db, author.id, incident_id), PublicIncident)


@router.post("/incidents/{incident_id}/transitions", response_model=PublicIncident)
def transition(incident_id: UUID, payload: TransitionInput, author: Analyst, db: Database):
    try:
        return run_operation(db, lambda: service.transition(db, author.id, incident_id, payload),
                             PublicIncident, commit=True)
    except IncidentTransitionError:
        raise HTTPException(status_code=409, detail="Transição de Incident não permitida.") from None
