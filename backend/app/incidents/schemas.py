from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, StrictStr, field_validator, model_validator

from app.core.pagination import PaginationQuery
from app.incidents.transitions import IncidentStatus


class IncidentsQuery(PaginationQuery):
    status: IncidentStatus | None = None
    severity: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"] | None = None
    asset_id: UUID | None = None
    opened_from: AwareDatetime | None = None
    opened_to: AwareDatetime | None = None

    @field_validator("opened_from", "opened_to", mode="before")
    @classmethod
    def explicit_datetime(cls, value):
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        if value is None or isinstance(value, datetime):
            return value
        raise ValueError("Data/hora ISO 8601 com fuso obrigatório.")

    @model_validator(mode="after")
    def valid_interval(self):
        if self.opened_from is not None and self.opened_to is not None and self.opened_from > self.opened_to:
            raise ValueError("Intervalo inválido.")
        return self


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
