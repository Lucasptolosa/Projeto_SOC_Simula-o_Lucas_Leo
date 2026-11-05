from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.incidents.transitions import IncidentStatus


class EscalationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class PublicIncident(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    alert_id: UUID
    analyst_id: UUID
    severity: str
    status: IncidentStatus
    opened_at: datetime
