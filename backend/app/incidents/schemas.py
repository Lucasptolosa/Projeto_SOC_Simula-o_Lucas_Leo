from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictStr, field_validator, model_validator

from app.incidents.transitions import IncidentStatus


class EscalationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class TransitionInput(EscalationInput):
    target_status: IncidentStatus
    containment_description: StrictStr | None = None
    resolution_conclusion: StrictStr | None = None

    @field_validator("containment_description", "resolution_conclusion")
    @classmethod
    def valid_text(cls, value: str | None) -> str | None:
        if value is None:
            return value
        if not value.strip() or "\x00" in value:
            raise ValueError("Texto obrigatório.")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Texto UTF-8 inválido.") from None
        return value

    @model_validator(mode="after")
    def compatible_fields(self):
        expected = {
            IncidentStatus.CONTAINED: "containment_description",
            IncidentStatus.RESOLVED: "resolution_conclusion",
        }.get(self.target_status)
        supplied = self.model_fields_set - {"target_status"}
        if supplied != ({expected} if expected else set()) or (
            expected and getattr(self, expected) is None
        ):
            raise ValueError("Campos incompatíveis com a transição.")
        return self


class PublicIncident(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    alert_id: UUID
    analyst_id: UUID
    severity: str
    status: IncidentStatus
    opened_at: datetime
    containment_description: str | None
    contained_by: UUID | None
    contained_at: datetime | None
    resolution_conclusion: str | None
    resolved_by: UUID | None
    resolved_at: datetime | None
