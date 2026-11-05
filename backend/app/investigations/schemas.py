from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StrictStr, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class StartInvestigationInput(Input):
    alert_id: UUID


class TextInput(Input):
    @field_validator("content", "justification", check_fields=False)
    @classmethod
    def valid_text(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("Texto obrigatório.")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Texto UTF-8 inválido.") from None
        return value


class ObservationInput(TextInput):
    content: StrictStr


class FalsePositiveInput(TextInput):
    justification: StrictStr


class PublicInvestigation(BaseModel):
    id: UUID
    alert_id: UUID
    analyst_id: UUID
    started_at: datetime
    status: str
    justification: str | None
    dismissed_by: UUID | None
    dismissed_at: datetime | None


class PublicObservation(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    investigation_id: UUID
    analyst_id: UUID
    content: str
    occurred_at: datetime
