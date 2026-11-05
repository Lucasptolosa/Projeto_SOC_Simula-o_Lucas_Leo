from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.incidents.models import Incident


def get(db: Session, incident_id: UUID, *, lock: bool = False) -> Incident | None:
    query = select(Incident).where(Incident.id == incident_id).execution_options(populate_existing=True)
    if lock:
        query = query.with_for_update()
    return db.scalar(query)


def exists_for_alert(db: Session, alert_id: UUID) -> bool:
    return db.scalar(select(Incident.id).where(Incident.alert_id == alert_id)) is not None
