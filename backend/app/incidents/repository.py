from datetime import datetime
from uuid import UUID

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.detection.models import AlertRecord
from app.incidents.models import Incident
from app.incidents.transitions import IncidentStatus


def get(db: Session, incident_id: UUID, *, lock: bool = False) -> Incident | None:
    query = select(Incident).where(Incident.id == incident_id).execution_options(populate_existing=True)
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def exists_for_alert(db: Session, alert_id: UUID) -> bool:
    return db.scalar(select(Incident.id).where(Incident.alert_id == alert_id)) is not None


def list_incidents(
    db: Session, page: int, page_size: int, status: IncidentStatus | None = None,
    severity: str | None = None, asset_id: UUID | None = None,
    opened_from: datetime | None = None, opened_to: datetime | None = None,
):
    filters = []
    if status is not None:
        filters.append(Incident.status == status)
    if severity is not None:
        filters.append(Incident.severity == severity)
    if asset_id is not None:
        filters.append(AlertRecord.asset_id == asset_id)
    if opened_from is not None:
        filters.append(Incident.opened_at >= opened_from)
    if opened_to is not None:
        filters.append(Incident.opened_at <= opened_to)
    join = Incident.alert_id == AlertRecord.id
    total = db.scalar(select(func.count()).select_from(Incident).join(AlertRecord, join).where(*filters))
    priority = case({"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}, value=Incident.severity, else_=4)
    query = select(Incident).join(AlertRecord, join).where(*filters).order_by(
        priority, Incident.opened_at.asc(), Incident.id.asc(),
    ).offset((page - 1) * page_size).limit(page_size)
    return total, db.scalars(query).all()
