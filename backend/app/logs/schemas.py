from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator

from app.logs.models import EventType


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
        if not value.strip():
            raise ValueError("Campo textual obrigatório.")
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


class ImportSummary(BaseModel):
    accepted: int
    rejected: int
    rejections: list[RejectedLog]
