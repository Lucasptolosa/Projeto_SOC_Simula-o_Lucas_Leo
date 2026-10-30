from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from app.users.models import UserRole


class PublicAuditLog(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    author_id: UUID
    action: str
    entity_type: str
    entity_id: str
    occurred_at: datetime
    old_role: UserRole | None = None
    new_role: UserRole | None = None
