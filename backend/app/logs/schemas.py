from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from app.logs.models import EVENT_ID_MAX_BYTES, EventType
from app.core.pagination import PaginationQuery


class LogInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    event_id: str = Field(strict=True)
    asset_id: UUID
    occurred_at: AwareDatetime
    event_type: EventType
    username: str = Field(strict=True)

    @field_validator("event_id", "username")
    @classmethod
    def nonempty_text(cls, value: str) -> str:
        if not value.strip() or "\x00" in value:
            raise ValueError("Campo textual obrigatório.")
        try:
            value.encode("utf-8")
        except UnicodeEncodeError:
            raise ValueError("Texto UTF-8 inválido.") from None
        return value

    @field_validator("event_id")
    @classmethod
    def bounded_identifier(cls, value: str) -> str:
        if len(value.encode("utf-8")) > EVENT_ID_MAX_BYTES:
            raise ValueError("Identificador excede o limite permitido.")
        return value

    @field_validator("occurred_at", mode="before")
    @classmethod
    def explicit_datetime(cls, value):
        if isinstance(value, str):
            return datetime.fromisoformat(value)
        if isinstance(value, datetime):
            return value
        raise ValueError("Data/hora com fuso obrigatório.")


class RejectedLog(BaseModel):
    position: int
    reason: str
    detail: str


class LogsQuery(PaginationQuery):
    asset_id: UUID | None = None
    event_type: EventType | None = None
    username: str | None = Field(default=None, strict=True)
    occurred_from: AwareDatetime | None = None
    occurred_to: AwareDatetime | None = None

    @field_validator("username")
    @classmethod
    def valid_username(cls, value):
        return None if value is None else LogInput.nonempty_text(value)

    @field_validator("occurred_from", "occurred_to", mode="before")
    @classmethod
    def explicit_period(cls, value):
        return None if value is None else LogInput.explicit_datetime(value)

    @model_validator(mode="after")
    def valid_interval(self):
        if self.occurred_from is not None and self.occurred_to is not None and self.occurred_from > self.occurred_to:
            raise ValueError("Intervalo inválido.")
        return self


class DetectionSummary(BaseModel):
    evaluated: int
    rejected: int
    rejections: list[RejectedLog]
    alerts_created: int


class ImportSummary(BaseModel):
    accepted: int
    rejected: int
    rejections: list[RejectedLog]
    detection: DetectionSummary
