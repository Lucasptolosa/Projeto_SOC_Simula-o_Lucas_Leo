from datetime import datetime, timezone
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.audit.service import append_audit
from app.investigations import repository
from app.investigations.models import Investigation, Observation
from app.investigations.rules import validate_false_positive, validate_start_investigation
from app.investigations.schemas import FalsePositiveInput, ObservationInput
from app.users.models import User, UserRole, UserStatus
from app.users.repository import current_user


class InvestigationServiceError(ValueError):
    pass


def authorize(db: Session, author_id: UUID, *, lock: bool = False) -> User:
    author = current_user(db, author_id, lock=lock)
    if author is None or author.status is not UserStatus.ACTIVE:
        raise InvestigationServiceError("inactive_author")
    if author.role is not UserRole.ANALYST:
        raise InvestigationServiceError("forbidden_author")
    return author


def context(db: Session, investigation_id: UUID, *, lock: bool = False):
    row = repository.investigation(db, investigation_id)
    if row is None:
        raise InvestigationServiceError("not_found")
    # Serializa pelo Alert
    alert = repository.alert(db, row.alert_id, lock=lock)
    return repository.investigation(db, investigation_id), alert


def public(row: Investigation, status: str) -> dict:
    return dict(
        id=row.id, alert_id=row.alert_id, analyst_id=row.analyst_id,
        started_at=row.started_at, status=status, justification=row.justification,
        dismissed_by=row.dismissed_by, dismissed_at=row.dismissed_at,
    )


def start(db: Session, author_id: UUID, alert_id: UUID) -> dict:
    author = authorize(db, author_id, lock=True)
    alert = repository.alert(db, alert_id, lock=True)
    if alert is None:
        raise InvestigationServiceError("not_found")
    status = validate_start_investigation(alert.status, actor_role=author.role.value)
    if repository.investigation_exists(db, alert_id):
        raise InvestigationServiceError("already_exists")
    row = Investigation(alert_id=alert_id, analyst_id=author.id,
                        started_at=datetime.now(timezone.utc))
    db.add(row)
    alert.status = status
    db.flush()
    return public(row, alert.status)


def get(db: Session, author_id: UUID, investigation_id: UUID) -> dict:
    authorize(db, author_id)
    row, alert = context(db, investigation_id)
    result = public(row, alert.status)
    result["incident_id"] = repository.incident_id(db, row.alert_id) if alert.status == "ESCALATED" else None
    return result


def add_observation(db: Session, author_id: UUID, investigation_id: UUID, content: str) -> dict:
    author = authorize(db, author_id, lock=True)
    row, _ = context(db, investigation_id, lock=True)
    try:
        payload = ObservationInput(content=content)
    except ValidationError:
        raise InvestigationServiceError("invalid_text") from None
    observation = Observation(investigation_id=row.id, analyst_id=author.id,
                              content=payload.content, occurred_at=datetime.now(timezone.utc))
    db.add(observation)
    db.flush()
    return {column.name: getattr(observation, column.name) for column in Observation.__table__.columns}


def list_observations(db: Session, author_id: UUID, investigation_id: UUID, page: int, page_size: int):
    authorize(db, author_id)
    context(db, investigation_id)
    return repository.observations(db, investigation_id, page, page_size)


def dismiss(db: Session, author_id: UUID, investigation_id: UUID, justification: str) -> dict:
    author = authorize(db, author_id, lock=True)
    row, alert = context(db, investigation_id, lock=True)
    status = validate_false_positive(alert.status, justification, actor_role=author.role.value)
    try:
        payload = FalsePositiveInput(justification=justification)
    except ValidationError:
        raise InvestigationServiceError("invalid_text") from None
    now = datetime.now(timezone.utc)
    old_status = alert.status
    row.justification, row.dismissed_by, row.dismissed_at = payload.justification, author.id, now
    alert.status = status
    append_audit(db, author_id=author.id, action="ALERT_DISMISSED", entity_type="ALERT",
                 entity_id=str(alert.id), old_status=old_status, new_status=status, occurred_at=now)
    db.flush()
    return public(row, alert.status)
