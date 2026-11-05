from uuid import UUID

from sqlalchemy.orm import Session

from app.alerts import repository
from app.alerts.schemas import AlertsQuery
from app.users import repository as user_repository
from app.users.models import UserRole, UserStatus


class AlertQueryError(ValueError):
    pass


def authorize(db: Session, author_id: UUID) -> None:
    author = user_repository.current_user(db, author_id)
    if author is None or author.status is not UserStatus.ACTIVE:
        raise AlertQueryError("inactive_author")
    if author.role is not UserRole.ANALYST:
        raise AlertQueryError("forbidden_author")


def list_alerts(db: Session, author_id: UUID, params: AlertsQuery) -> dict:
    authorize(db, author_id)
    return repository.list_alerts(db, params)


def get_alert(db: Session, author_id: UUID, alert_id: UUID) -> dict:
    authorize(db, author_id)
    row = repository.alert(db, alert_id)
    if row is None:
        raise AlertQueryError("not_found")
    return dict(row) | {"related_logs": repository.evidence(db, alert_id)}
