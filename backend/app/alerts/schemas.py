from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator, model_validator

from app.core.pagination import PaginationQuery
from app.logs.models import EventType


Severity = Literal["LOW", "MEDIUM", "HIGH", "CRITICAL"]
AlertStatus = Literal["NEW", "IN_REVIEW", "DISMISSED", "ESCALATED"]


class AlertsQuery(PaginationQuery):
    severity: Severity | None = None
    status: AlertStatus | None = None
    asset_id: UUID | None = None
    rule_id: Literal["DR01", "DR02", "DR03"] | None = None
    created_from: AwareDatetime | None = None
    created_to: AwareDatetime | None = None

    @field_validator("created_from", "created_to", mode="before")
    @classmethod
    def explicit_datetime(cls, value):
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        if value is None or isinstance(value, datetime):
            return value
        raise ValueError("Data/hora ISO 8601 com fuso obrigatório.")

    @model_validator(mode="after")
    def valid_interval(self):
        if self.created_from is not None and self.created_to is not None and self.created_from > self.created_to:
            raise ValueError("Intervalo inválido.")
        return self


class DetailQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class PublicAlert(BaseModel):
    id: UUID
    rule_id: str
    asset_id: UUID
    username: str
    severity: Severity
    status: AlertStatus
    created_at: AwareDatetime


class PublicLog(BaseModel):
    event_id: str
    asset_id: UUID
    occurred_at: AwareDatetime
    event_type: EventType
    username: str


class AlertDetail(PublicAlert):
    investigation_id: UUID | None
    incident_id: UUID | None
    related_logs: list[PublicLog]
