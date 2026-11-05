from uuid import UUID

from fastapi import APIRouter

from app.incidents import service
from app.incidents.schemas import EscalationInput, PublicIncident
from app.investigations.router import Analyst, Database, run_operation


router = APIRouter(tags=["Incidents"])


@router.post("/investigations/{investigation_id}/escalate", response_model=PublicIncident, status_code=201)
def escalate(investigation_id: UUID, author: Analyst, db: Database, payload: EscalationInput | None = None):
    return run_operation(db, lambda: service.escalate(db, author.id, investigation_id),
                         PublicIncident, commit=True)


@router.get("/incidents/{incident_id}", response_model=PublicIncident)
def get(incident_id: UUID, author: Analyst, db: Database):
    return run_operation(db, lambda: service.get(db, author.id, incident_id), PublicIncident)
